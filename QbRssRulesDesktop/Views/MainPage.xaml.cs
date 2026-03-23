using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Text.Json;
using Microsoft.UI.Dispatching;
using Microsoft.Web.WebView2.Core;

namespace QbRssRulesDesktop.Views
{
    public partial class MainPage : Page
    {
        private static readonly HttpClient BackendProbeClient = new()
        {
            Timeout = TimeSpan.FromSeconds(2),
        };

        private const string DefaultBackendUrl = "http://127.0.0.1:8000";
        private const string RequiredDesktopBackendContract = "2026-03-22";
        private const string ManagedBackendStateFileName = "desktop-managed-backend.json";
        private const int ManagedBackendPortSearchLimit = 32;
        private const int ReconnectAttemptLimit = 30;
        private Uri backendUri;
        private readonly DispatcherQueue dispatcherQueue;
        private readonly DispatcherQueueTimer reconnectTimer;
        private readonly string? repositoryRoot;
        private readonly bool usesConfiguredBackendUrl;
        private Process? managedBackendProcess;
        private bool autoStartAttempted;
        private bool isDisposing;
        private bool hasAttachedCloseHandlers;
        private int remainingReconnectAttempts;
        private string lastBackendProbeFailure = "";

        private sealed record ManagedBackendState(int OwnerPid, int BackendPid, string BackendUrl, string RepositoryRoot, string StartedAtUtc);
        private sealed record BackendConfiguration(Uri Uri, bool UsesConfiguredUrl);

        public MainPage()
        {
            InitializeComponent();
            var backendConfiguration = ResolveBackendConfiguration();
            backendUri = backendConfiguration.Uri;
            usesConfiguredBackendUrl = backendConfiguration.UsesConfiguredUrl;
            repositoryRoot = ResolveRepositoryRoot();
            dispatcherQueue = DispatcherQueue.GetForCurrentThread();
            reconnectTimer = dispatcherQueue.CreateTimer();
            reconnectTimer.Interval = TimeSpan.FromSeconds(2);
            reconnectTimer.Tick += OnReconnectTimerTick;
            Loaded += OnLoaded;
            Unloaded += OnUnloaded;
        }

        private static BackendConfiguration ResolveBackendConfiguration()
        {
            var configuredUrl = Environment.GetEnvironmentVariable("QB_RSS_DESKTOP_URL");
            if (!string.IsNullOrWhiteSpace(configuredUrl) &&
                Uri.TryCreate(configuredUrl, UriKind.Absolute, out var configuredUri) &&
                (configuredUri.Scheme == Uri.UriSchemeHttp || configuredUri.Scheme == Uri.UriSchemeHttps))
            {
                return new BackendConfiguration(configuredUri, UsesConfiguredUrl: true);
            }

            return new BackendConfiguration(new Uri(DefaultBackendUrl), UsesConfiguredUrl: false);
        }

        private static string? ResolveRepositoryRoot()
        {
            var current = new DirectoryInfo(AppContext.BaseDirectory);
            while (current is not null)
            {
                var scriptsPath = Path.Combine(current.FullName, "scripts", "run_dev.bat");
                var appPath = Path.Combine(current.FullName, "app", "main.py");
                if (File.Exists(scriptsPath) && File.Exists(appPath))
                {
                    return current.FullName;
                }

                current = current.Parent;
            }

            return null;
        }

        private async void OnLoaded(object sender, RoutedEventArgs e)
        {
            Loaded -= OnLoaded;
            EnsureCloseHandlers();
            CleanupStaleManagedBackend();

            if (await IsBackendReachableAsync())
            {
                NavigateToBackend();
                return;
            }

            if (!autoStartAttempted)
            {
                autoStartAttempted = true;
                TryStartBackendProcess(autoTriggered: true);
                return;
            }

            ShowOfflineState(LastBackendProbeFailureOrDefault("Backend is not running."));
        }

        private void OnUnloaded(object sender, RoutedEventArgs e)
        {
            DisposeDesktopSession();
        }

        private void NavigateToBackend()
        {
            reconnectTimer.Stop();
            ConnectionStatusText.Text = $"Connecting to {backendUri}...";
            OfflinePanel.Visibility = Visibility.Collapsed;
            AppWebView.Visibility = Visibility.Visible;

            try
            {
                AppWebView.Source = BuildDesktopNavigationUri();
            }
            catch (Exception ex)
            {
                ShowOfflineState($"Couldn't start embedded browser: {ex.Message}");
            }
        }

        private void OnNavigationCompleted(WebView2 sender, CoreWebView2NavigationCompletedEventArgs args)
        {
            if (args.IsSuccess)
            {
                ConnectionStatusText.Text = $"Connected to {backendUri}";
                OfflinePanel.Visibility = Visibility.Collapsed;
                AppWebView.Visibility = Visibility.Visible;
                return;
            }

            ShowOfflineState($"Navigation failed: {args.WebErrorStatus}");
        }

        private void ShowOfflineState(string detail)
        {
            ConnectionStatusText.Text = "Backend unavailable";
            var guidance = repositoryRoot is null
                ? "Clone the repository locally so the desktop app can build and launch the backend for you."
                : "You can also run scripts\\run_dev.bat api (API only) or scripts\\run_dev.bat full (API + desktop) manually.";
            OfflineMessageText.Text = $"Unable to load {backendUri}. {detail} {guidance}";
            AppWebView.Visibility = Visibility.Collapsed;
            OfflinePanel.Visibility = Visibility.Visible;
        }

        private void OnRetryClicked(object sender, RoutedEventArgs e)
        {
            _ = RetryConnectAsync();
        }

        private async void OnReconnectTimerTick(DispatcherQueueTimer sender, object args)
        {
            if (await IsBackendReachableAsync())
            {
                reconnectTimer.Stop();
                NavigateToBackend();
                return;
            }

            remainingReconnectAttempts--;
            ConnectionStatusText.Text = $"Waiting for backend startup... ({remainingReconnectAttempts})";

            if (remainingReconnectAttempts <= 0)
            {
                reconnectTimer.Stop();
                ShowOfflineState(LastBackendProbeFailureOrDefault("Backend did not become available in time."));
            }
        }

        private async Task<bool> IsBackendReachableAsync()
        {
            lastBackendProbeFailure = "";
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, new Uri(backendUri, "/health"));
                using var response = await BackendProbeClient.SendAsync(request);
                if (!response.IsSuccessStatusCode)
                {
                    lastBackendProbeFailure = $"Health probe returned HTTP {(int)response.StatusCode}.";
                    return false;
                }

                using var healthDocument = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
                var root = healthDocument.RootElement;
                var status = root.TryGetProperty("status", out var statusElement) ? statusElement.GetString() : "";
                if (!string.Equals(status, "ok", StringComparison.OrdinalIgnoreCase))
                {
                    lastBackendProbeFailure = "Health probe did not report an ok status.";
                    return false;
                }

                var contract = root.TryGetProperty("desktop_backend_contract", out var contractElement)
                    ? contractElement.GetString()
                    : "";
                if (!string.Equals(contract, RequiredDesktopBackendContract, StringComparison.Ordinal))
                {
                    lastBackendProbeFailure = string.IsNullOrWhiteSpace(contract)
                        ? $"An incompatible backend is already listening at {backendUri}; it does not expose desktop contract {RequiredDesktopBackendContract}."
                        : $"An incompatible backend is already listening at {backendUri}; expected desktop contract {RequiredDesktopBackendContract}, got {contract}.";
                    return false;
                }

                return true;
            }
            catch
            {
                lastBackendProbeFailure = $"No compatible backend responded at {backendUri}.";
                return false;
            }
        }

        private bool TryStartBackendProcess(bool autoTriggered)
        {
            try
            {
                PrepareManagedBackendUri();
            }
            catch (Exception ex)
            {
                ShowOfflineState(ex.Message);
                return false;
            }

            if (repositoryRoot is null)
            {
                ShowOfflineState("Unable to locate repository root for backend startup. Run scripts\\run_dev.bat api or scripts\\run_dev.bat full.");
                return false;
            }

            if (managedBackendProcess is { HasExited: false })
            {
                ConnectionStatusText.Text = "Backend is already starting...";
                return true;
            }

            var pythonExecutable = ResolvePythonExecutable();
            if (pythonExecutable is null)
            {
                ShowOfflineState("Could not find python/pythonw in .venv or PATH. Run scripts\\run_dev.bat api or containerize the API manually.");
                return false;
            }

            try
            {
                var startInfo = new ProcessStartInfo
                {
                    FileName = pythonExecutable,
                    Arguments = BuildBackendArguments(),
                    WorkingDirectory = repositoryRoot,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                startInfo.Environment["QB_RSS_DESKTOP_MANAGED"] = "1";
                startInfo.Environment["QB_RSS_DESKTOP_OWNER_PID"] = Environment.ProcessId.ToString();
                startInfo.Environment["QB_RSS_DESKTOP_URL"] = backendUri.ToString();
                var process = Process.Start(startInfo);

                if (process is null)
                {
                    ShowOfflineState("Backend process did not start.");
                    return false;
                }

                process.EnableRaisingEvents = true;
                process.Exited += OnManagedBackendExited;
                managedBackendProcess = process;
                WriteManagedBackendState(process.Id);

                remainingReconnectAttempts = ReconnectAttemptLimit;
                ConnectionStatusText.Text = autoTriggered
                    ? "Starting backend automatically..."
                    : "Starting backend...";
                OfflineMessageText.Text = $"Launching FastAPI via {Path.GetFileName(pythonExecutable)} (target {backendUri}).";
                OfflinePanel.Visibility = Visibility.Visible;
                AppWebView.Visibility = Visibility.Collapsed;
                reconnectTimer.Start();
                return true;
            }
            catch (Exception ex)
            {
                ShowOfflineState($"Automatic backend start failed: {ex.Message}");
                return false;
            }
        }

        private string BuildBackendArguments()
        {
            var host = backendUri.Host;
            var port = backendUri.Port;
            return $"-m uvicorn app.main:create_app --factory --host {host} --port {port} --reload";
        }

        private string? ResolvePythonExecutable()
        {
            if (repositoryRoot is null)
            {
                return null;
            }

            var scriptsPath = Path.Combine(repositoryRoot, ".venv", "Scripts");
            foreach (var executable in new[] { "python.exe", "pythonw.exe" })
            {
                var candidate = Path.Combine(scriptsPath, executable);
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }

            return FindExecutableOnPath("python.exe", "pythonw.exe");
        }

        private static string? FindExecutableOnPath(params string[] executableNames)
        {
            var pathValue = Environment.GetEnvironmentVariable("PATH");
            if (string.IsNullOrWhiteSpace(pathValue))
            {
                return null;
            }

            foreach (var executable in executableNames)
            {
                foreach (var segment in pathValue.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
                {
                    var trimmed = segment.Trim();
                    if (string.IsNullOrWhiteSpace(trimmed))
                    {
                        continue;
                    }

                    var candidate = Path.Combine(trimmed, executable);
                    if (File.Exists(candidate))
                    {
                        return candidate;
                    }
                }
            }

            return null;
        }

        private void OnManagedBackendExited(object? sender, EventArgs e)
        {
            dispatcherQueue.TryEnqueue(() =>
            {
                if (managedBackendProcess is not null)
                {
                    managedBackendProcess.Dispose();
                    managedBackendProcess = null;
                }

                DeleteManagedBackendState();
                reconnectTimer.Stop();
                if (!isDisposing)
                {
                    ShowOfflineState("Backend process stopped.");
                }
            });
        }

        private void StopManagedBackendProcess()
        {
            if (managedBackendProcess is null)
            {
                return;
            }

            try
            {
                if (!managedBackendProcess.HasExited)
                {
                    managedBackendProcess.Kill(true);
                    managedBackendProcess.WaitForExit(TimeSpan.FromSeconds(2));
                }
            }
            catch
            {
                // Ignore cleanup failures; the OS will tear down the child process.
            }
            finally
            {
                managedBackendProcess.Dispose();
                managedBackendProcess = null;
                DeleteManagedBackendState();
            }
        }

        private void OnStartBackendClicked(object sender, RoutedEventArgs e)
        {
            _ = TryStartBackendProcess(autoTriggered: false);
        }

        private void OnOpenInBrowserClicked(object sender, RoutedEventArgs e)
        {
            try
            {
                Process.Start(
                    new ProcessStartInfo
                    {
                        FileName = backendUri.ToString(),
                        UseShellExecute = true,
                    });
            }
            catch (Exception ex)
            {
                ShowOfflineState($"Could not open external browser: {ex.Message}");
            }
        }

        private void PrepareManagedBackendUri()
        {
            if (usesConfiguredBackendUrl || !backendUri.IsLoopback || backendUri.Scheme != Uri.UriSchemeHttp)
            {
                return;
            }

            if (IsLoopbackPortAvailable(backendUri.Port))
            {
                return;
            }

            var fallbackPort = FindAvailableLoopbackPort(backendUri.Port + 1, ManagedBackendPortSearchLimit);
            if (fallbackPort is null)
            {
                throw new InvalidOperationException(
                    $"No local port was available for a managed backend near {backendUri.Port}. {LastBackendProbeFailureOrDefault("Stop the stale backend and retry.")}"
                );
            }

            backendUri = new UriBuilder(backendUri)
            {
                Port = fallbackPort.Value,
            }.Uri;
        }

        private static bool IsLoopbackPortAvailable(int port)
        {
            try
            {
                using var listener = new TcpListener(IPAddress.Loopback, port);
                listener.Start();
                listener.Stop();
                return true;
            }
            catch (SocketException)
            {
                return false;
            }
        }

        private static int? FindAvailableLoopbackPort(int startPort, int maxAttempts)
        {
            for (var offset = 0; offset < maxAttempts; offset++)
            {
                var candidatePort = startPort + offset;
                if (candidatePort < 1 || candidatePort > IPEndPoint.MaxPort)
                {
                    break;
                }

                if (IsLoopbackPortAvailable(candidatePort))
                {
                    return candidatePort;
                }
            }

            return null;
        }

        private async Task RetryConnectAsync()
        {
            if (await IsBackendReachableAsync())
            {
                NavigateToBackend();
                return;
            }

            ShowOfflineState(LastBackendProbeFailureOrDefault("Backend is not running."));
        }

        private string LastBackendProbeFailureOrDefault(string fallback)
        {
            return string.IsNullOrWhiteSpace(lastBackendProbeFailure) ? fallback : lastBackendProbeFailure;
        }

        private void EnsureCloseHandlers()
        {
            if (hasAttachedCloseHandlers)
            {
                return;
            }

            if (App.MainWindow is not null)
            {
                App.MainWindow.Closed += OnHostWindowClosed;
            }

            AppDomain.CurrentDomain.ProcessExit += OnProcessExit;
            hasAttachedCloseHandlers = true;
        }

        private void OnHostWindowClosed(object sender, WindowEventArgs args)
        {
            DisposeDesktopSession();
        }

        private void OnProcessExit(object? sender, EventArgs args)
        {
            DisposeDesktopSession();
        }

        private void DisposeDesktopSession()
        {
            if (isDisposing)
            {
                return;
            }

            isDisposing = true;
            reconnectTimer.Stop();
            StopManagedBackendProcess();
            if (hasAttachedCloseHandlers)
            {
                if (App.MainWindow is not null)
                {
                    App.MainWindow.Closed -= OnHostWindowClosed;
                }

                AppDomain.CurrentDomain.ProcessExit -= OnProcessExit;
                hasAttachedCloseHandlers = false;
            }
            isDisposing = false;
        }

        private Uri BuildDesktopNavigationUri()
        {
            var builder = new UriBuilder(backendUri);
            var cacheBustQuery = $"desktop_client=1&desktop_launch={DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()}";
            builder.Query = string.IsNullOrWhiteSpace(builder.Query)
                ? cacheBustQuery
                : $"{builder.Query.TrimStart('?')}&{cacheBustQuery}";
            return builder.Uri;
        }

        private string? ManagedBackendStatePath()
        {
            if (repositoryRoot is null)
            {
                return null;
            }

            return Path.Combine(repositoryRoot, "logs", ManagedBackendStateFileName);
        }

        private void WriteManagedBackendState(int backendPid)
        {
            var statePath = ManagedBackendStatePath();
            if (string.IsNullOrWhiteSpace(statePath) || repositoryRoot is null)
            {
                return;
            }

            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(statePath)!);
                var state = new ManagedBackendState(
                    Environment.ProcessId,
                    backendPid,
                    backendUri.ToString(),
                    repositoryRoot,
                    DateTimeOffset.UtcNow.ToString("O"));
                File.WriteAllText(statePath, JsonSerializer.Serialize(state));
            }
            catch
            {
                // Ignore marker persistence failures; the running process remains authoritative.
            }
        }

        private void DeleteManagedBackendState(bool force = false)
        {
            var statePath = ManagedBackendStatePath();
            if (string.IsNullOrWhiteSpace(statePath) || !File.Exists(statePath))
            {
                return;
            }

            try
            {
                if (!force)
                {
                    var stateJson = File.ReadAllText(statePath);
                    var state = JsonSerializer.Deserialize<ManagedBackendState>(stateJson);
                    if (state is not null && state.OwnerPid != Environment.ProcessId)
                    {
                        return;
                    }
                }

                File.Delete(statePath);
            }
            catch
            {
                // Ignore marker cleanup failures; stale cleanup on the next launch will retry.
            }
        }

        private void CleanupStaleManagedBackend()
        {
            var statePath = ManagedBackendStatePath();
            if (string.IsNullOrWhiteSpace(statePath) || !File.Exists(statePath))
            {
                return;
            }

            try
            {
                var stateJson = File.ReadAllText(statePath);
                var state = JsonSerializer.Deserialize<ManagedBackendState>(stateJson);
                if (state is null)
                {
                    DeleteManagedBackendState(force: true);
                    return;
                }

                if (state.OwnerPid == Environment.ProcessId)
                {
                    return;
                }

                if (IsProcessAlive(state.OwnerPid))
                {
                    return;
                }

                TryKillProcessTree(state.BackendPid);
                DeleteManagedBackendState(force: true);
            }
            catch
            {
                DeleteManagedBackendState(force: true);
            }
        }

        private static bool IsProcessAlive(int pid)
        {
            try
            {
                using var process = Process.GetProcessById(pid);
                return !process.HasExited;
            }
            catch
            {
                return false;
            }
        }

        private static void TryKillProcessTree(int pid)
        {
            try
            {
                using var process = Process.GetProcessById(pid);
                if (!process.HasExited)
                {
                    process.Kill(true);
                    process.WaitForExit(TimeSpan.FromSeconds(2));
                }
            }
            catch
            {
                // Ignore stale cleanup failures; the next launch can retry.
            }
        }
    }
}
