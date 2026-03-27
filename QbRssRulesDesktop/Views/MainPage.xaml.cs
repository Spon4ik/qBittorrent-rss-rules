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
        private const string RequiredDesktopBackendAppVersion = "0.7.6";
        private const string ManagedBackendStateFileName = "desktop-managed-backend.json";
        private const int ManagedBackendPortSearchLimit = 32;
        private const int ReconnectAttemptLimit = 30;
        private Uri backendUri;
        private readonly DispatcherQueue dispatcherQueue;
        private readonly DispatcherQueueTimer reconnectTimer;
        private readonly DispatcherQueueTimer localChangeDebounceTimer;
        private readonly DispatcherQueueTimer localAppPollTimer;
        private readonly List<FileSystemWatcher> localAppWatchers = new();
        private readonly string? repositoryRoot;
        private readonly bool usesConfiguredBackendUrl;
        private Process? managedBackendProcess;
        private bool autoStartAttempted;
        private bool isDisposing;
        private bool hasAttachedCloseHandlers;
        private bool hasAttachedWindowActivatedHandler;
        private int remainingReconnectAttempts;
        private long appliedLocalAppFreshnessTicks;
        private long requiredLocalAppFreshnessTicks;
        private long pendingNavigationFreshnessTicks;
        private string pendingLocalRefreshDetail = "Detected local app changes.";
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
            localChangeDebounceTimer = dispatcherQueue.CreateTimer();
            localChangeDebounceTimer.Interval = TimeSpan.FromMilliseconds(750);
            localChangeDebounceTimer.Tick += OnLocalChangeDebounceTick;
            localAppPollTimer = dispatcherQueue.CreateTimer();
            localAppPollTimer.Interval = TimeSpan.FromSeconds(2);
            localAppPollTimer.Tick += OnLocalAppPollTick;
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
                var appPath = Path.Combine(current.FullName, "app", "main.py");
                var devScriptPath = Path.Combine(current.FullName, "scripts", "run_dev.bat");
                var bundledPythonPath = Path.Combine(current.FullName, "python", "python.exe");
                var bundledPythonwPath = Path.Combine(current.FullName, "python", "pythonw.exe");
                var venvPythonPath = Path.Combine(current.FullName, ".venv", "Scripts", "python.exe");
                var venvPythonwPath = Path.Combine(current.FullName, ".venv", "Scripts", "pythonw.exe");
                if (
                    File.Exists(appPath)
                    && (
                        File.Exists(devScriptPath)
                        || File.Exists(bundledPythonPath)
                        || File.Exists(bundledPythonwPath)
                        || File.Exists(venvPythonPath)
                        || File.Exists(venvPythonwPath)
                    )
                )
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
            InitializeLocalAppFreshnessTracking();
            StartLocalAppWatchers();
            if (IsLocalAppWatchEnabled())
            {
                localAppPollTimer.Start();
            }
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
            pendingNavigationFreshnessTicks = requiredLocalAppFreshnessTicks;
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
                appliedLocalAppFreshnessTicks = Math.Max(appliedLocalAppFreshnessTicks, pendingNavigationFreshnessTicks);
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
                ? "Install the full qB RSS Rules Desktop bundle so the desktop app can launch the backend for you."
                : HasDevCheckoutScripts()
                    ? "You can also run scripts\\run_dev.bat api (API only) or scripts\\run_dev.bat full (API + desktop) manually."
                    : "Reinstall the full qB RSS Rules Desktop bundle if the bundled backend runtime is missing or damaged.";
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

                var appVersion = root.TryGetProperty("app_version", out var appVersionElement)
                    ? appVersionElement.GetString()
                    : "";
                if (!string.Equals(appVersion, RequiredDesktopBackendAppVersion, StringComparison.Ordinal))
                {
                    lastBackendProbeFailure = string.IsNullOrWhiteSpace(appVersion)
                        ? $"An incompatible backend is already listening at {backendUri}; expected app version {RequiredDesktopBackendAppVersion}."
                        : $"An incompatible backend is already listening at {backendUri}; expected app version {RequiredDesktopBackendAppVersion}, got {appVersion}.";
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
                ShowOfflineState("Unable to locate the app root for backend startup.");
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
                ShowOfflineState("Could not find the bundled Python runtime or a repo .venv for backend startup.");
                return false;
            }

            try
            {
                var startInfo = new ProcessStartInfo
                {
                    FileName = pythonExecutable,
                    Arguments = BuildBackendArguments(enableReload: !IsBundledPythonExecutable(pythonExecutable)),
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

        private string BuildBackendArguments(bool enableReload)
        {
            var host = backendUri.Host;
            var port = backendUri.Port;
            return enableReload
                ? $"-m uvicorn app.main:create_app --factory --host {host} --port {port} --reload"
                : $"-m uvicorn app.main:create_app --factory --host {host} --port {port}";
        }

        private string? ResolvePythonExecutable()
        {
            if (repositoryRoot is null)
            {
                return null;
            }

            var bundledPythonPath = Path.Combine(repositoryRoot, "python");
            foreach (var executable in new[] { "python.exe", "pythonw.exe" })
            {
                var candidate = Path.Combine(bundledPythonPath, executable);
                if (File.Exists(candidate))
                {
                    return candidate;
                }
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

        private bool HasDevCheckoutScripts()
        {
            return repositoryRoot is not null
                && File.Exists(Path.Combine(repositoryRoot, "scripts", "run_dev.bat"));
        }

        private bool IsLocalAppWatchEnabled()
        {
            return repositoryRoot is not null
                && HasDevCheckoutScripts()
                && Directory.Exists(Path.Combine(repositoryRoot, "app"));
        }

        private void InitializeLocalAppFreshnessTracking()
        {
            var freshnessTicks = ComputeLocalAppFreshnessTicks();
            requiredLocalAppFreshnessTicks = freshnessTicks;
            appliedLocalAppFreshnessTicks = freshnessTicks;
            pendingNavigationFreshnessTicks = freshnessTicks;
        }

        private void StartLocalAppWatchers()
        {
            if (!IsLocalAppWatchEnabled() || localAppWatchers.Count > 0 || repositoryRoot is null)
            {
                return;
            }

            var appRoot = Path.Combine(repositoryRoot, "app");
            var watcher = new FileSystemWatcher(appRoot)
            {
                IncludeSubdirectories = true,
                NotifyFilter = NotifyFilters.FileName | NotifyFilters.DirectoryName | NotifyFilters.LastWrite,
                Filter = "*.*",
                EnableRaisingEvents = true,
            };
            watcher.Changed += OnLocalAppFileChanged;
            watcher.Created += OnLocalAppFileChanged;
            watcher.Deleted += OnLocalAppFileChanged;
            watcher.Renamed += OnLocalAppFileRenamed;
            localAppWatchers.Add(watcher);
        }

        private void StopLocalAppWatchers()
        {
            foreach (var watcher in localAppWatchers)
            {
                watcher.EnableRaisingEvents = false;
                watcher.Changed -= OnLocalAppFileChanged;
                watcher.Created -= OnLocalAppFileChanged;
                watcher.Deleted -= OnLocalAppFileChanged;
                watcher.Renamed -= OnLocalAppFileRenamed;
                watcher.Dispose();
            }

            localAppWatchers.Clear();
        }

        private void OnLocalAppFileChanged(object sender, FileSystemEventArgs args)
        {
            HandlePotentialLocalAppChange(args.FullPath);
        }

        private void OnLocalAppFileRenamed(object sender, RenamedEventArgs args)
        {
            HandlePotentialLocalAppChange(args.OldFullPath);
            HandlePotentialLocalAppChange(args.FullPath);
        }

        private void HandlePotentialLocalAppChange(string path)
        {
            if (!IsRelevantLocalAppPath(path))
            {
                return;
            }

            dispatcherQueue.TryEnqueue(() =>
            {
                requiredLocalAppFreshnessTicks = Math.Max(requiredLocalAppFreshnessTicks, ComputeLocalAppFreshnessTicks());
                pendingLocalRefreshDetail = "Detected local app changes. Reloading desktop session.";
                localChangeDebounceTimer.Stop();
                localChangeDebounceTimer.Start();
            });
        }

        private static bool IsRelevantLocalAppPath(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                return false;
            }

            if (path.Contains($"{Path.DirectorySeparatorChar}__pycache__{Path.DirectorySeparatorChar}", StringComparison.OrdinalIgnoreCase)
                || path.EndsWith(".pyc", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            return Path.GetExtension(path) switch
            {
                ".css" => true,
                ".html" => true,
                ".js" => true,
                ".json" => true,
                ".py" => true,
                _ => false,
            };
        }

        private long ComputeLocalAppFreshnessTicks()
        {
            if (!IsLocalAppWatchEnabled() || repositoryRoot is null)
            {
                return 0;
            }

            try
            {
                return Directory
                    .EnumerateFiles(Path.Combine(repositoryRoot, "app"), "*.*", SearchOption.AllDirectories)
                    .Where(IsRelevantLocalAppPath)
                    .Select(path => new FileInfo(path).LastWriteTimeUtc.Ticks)
                    .DefaultIfEmpty(0)
                    .Max();
            }
            catch
            {
                return requiredLocalAppFreshnessTicks;
            }
        }

        private async void OnLocalChangeDebounceTick(DispatcherQueueTimer sender, object args)
        {
            localChangeDebounceTimer.Stop();
            await RefreshForLocalAppChangesAsync(pendingLocalRefreshDetail);
        }

        private async void OnLocalAppPollTick(DispatcherQueueTimer sender, object args)
        {
            if (!IsLocalAppWatchEnabled())
            {
                return;
            }

            var freshnessTicks = ComputeLocalAppFreshnessTicks();
            if (freshnessTicks <= requiredLocalAppFreshnessTicks)
            {
                return;
            }

            requiredLocalAppFreshnessTicks = freshnessTicks;
            await RefreshForLocalAppChangesAsync("Detected local app changes. Reloading desktop session.");
        }

        private async Task RefreshForLocalAppChangesAsync(string detail)
        {
            if (!IsLocalAppWatchEnabled())
            {
                return;
            }

            requiredLocalAppFreshnessTicks = Math.Max(requiredLocalAppFreshnessTicks, ComputeLocalAppFreshnessTicks());
            if (requiredLocalAppFreshnessTicks <= appliedLocalAppFreshnessTicks)
            {
                return;
            }

            reconnectTimer.Stop();
            ConnectionStatusText.Text = "Refreshing desktop session...";
            OfflineMessageText.Text = detail;
            AppWebView.Visibility = Visibility.Collapsed;
            OfflinePanel.Visibility = Visibility.Visible;

            if (await IsBackendReachableAsync())
            {
                NavigateToBackend();
                return;
            }

            remainingReconnectAttempts = ReconnectAttemptLimit;
            ConnectionStatusText.Text = $"Refreshing desktop session... ({remainingReconnectAttempts})";
            OfflineMessageText.Text = $"{detail} {LastBackendProbeFailureOrDefault("Waiting for a compatible backend.")}";
            reconnectTimer.Start();
        }

        private bool IsBundledPythonExecutable(string pythonExecutable)
        {
            if (repositoryRoot is null)
            {
                return false;
            }

            var bundledPythonRoot = Path.Combine(repositoryRoot, "python");
            return pythonExecutable.StartsWith(bundledPythonRoot, StringComparison.OrdinalIgnoreCase);
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

        private bool StopManagedBackendProcess()
        {
            if (managedBackendProcess is null)
            {
                return false;
            }

            var process = managedBackendProcess;
            var backendPid = process.Id;
            var stopped = false;

            try
            {
                if (process.HasExited)
                {
                    stopped = true;
                }
                else
                {
                    try
                    {
                        process.Kill(true);
                    }
                    catch
                    {
                        // Keep going and try the stronger fallback path below.
                    }

                    stopped = process.WaitForExit(TimeSpan.FromSeconds(3));
                    if (!stopped)
                    {
                        stopped = TryKillProcessTree(backendPid);
                    }
                }
            }
            catch
            {
                stopped = false;
            }

            if (!stopped && !IsProcessAlive(backendPid))
            {
                stopped = true;
            }

            if (!stopped)
            {
                return false;
            }

            try
            {
                process.Dispose();
            }
            catch
            {
                // Ignore cleanup failures; the process is already gone or being torn down.
            }

            managedBackendProcess = null;
            DeleteManagedBackendState();
            return true;
        }

        private void OnStartBackendClicked(object sender, RoutedEventArgs e)
        {
            _ = TryStartBackendProcess(autoTriggered: false);
        }

        private void OnShutdownEngineClicked(object sender, RoutedEventArgs e)
        {
            reconnectTimer.Stop();
            localChangeDebounceTimer.Stop();
            if (managedBackendProcess is null || managedBackendProcess.HasExited)
            {
                ConnectionStatusText.Text = "Managed backend is not running";
                if (OfflinePanel.Visibility == Visibility.Visible)
                {
                    OfflineMessageText.Text = "No desktop-managed backend is currently running for this session.";
                }
                return;
            }

            if (StopManagedBackendProcess())
            {
                ShowOfflineState("Managed backend shut down. Use Start Backend to launch it again.");
                return;
            }

            ShowOfflineState(
                "Managed backend shutdown could not be confirmed yet. The shell kept the ownership marker so a later retry can finish stopping it."
            );
        }

        private void OnExitClicked(object sender, RoutedEventArgs e)
        {
            App.MainWindow?.Close();
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
            requiredLocalAppFreshnessTicks = Math.Max(requiredLocalAppFreshnessTicks, ComputeLocalAppFreshnessTicks());
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
                App.MainWindow.Activated += OnHostWindowActivated;
                hasAttachedWindowActivatedHandler = true;
            }

            AppDomain.CurrentDomain.ProcessExit += OnProcessExit;
            hasAttachedCloseHandlers = true;
        }

        private async void OnHostWindowActivated(object sender, WindowActivatedEventArgs args)
        {
            if (args.WindowActivationState == WindowActivationState.Deactivated)
            {
                return;
            }

            await RefreshForLocalAppChangesAsync("Applying newer local app changes.");
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
            localChangeDebounceTimer.Stop();
            localAppPollTimer.Stop();
            StopLocalAppWatchers();
            StopManagedBackendProcess();
            if (hasAttachedCloseHandlers)
            {
                if (App.MainWindow is not null)
                {
                    App.MainWindow.Closed -= OnHostWindowClosed;
                    if (hasAttachedWindowActivatedHandler)
                    {
                        App.MainWindow.Activated -= OnHostWindowActivated;
                        hasAttachedWindowActivatedHandler = false;
                    }
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

                if (TryKillProcessTree(state.BackendPid) || !IsProcessAlive(state.BackendPid))
                {
                    DeleteManagedBackendState(force: true);
                }
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

        private static bool TryKillProcessTree(int pid)
        {
            if (pid <= 0)
            {
                return false;
            }

            if (!IsProcessAlive(pid))
            {
                return true;
            }

            try
            {
                using var process = Process.GetProcessById(pid);
                if (!process.HasExited)
                {
                    process.Kill(true);
                    if (process.WaitForExit(TimeSpan.FromSeconds(3)))
                    {
                        return true;
                    }
                }
            }
            catch
            {
                // Ignore stale cleanup failures and fall back to a stronger termination path.
            }

            try
            {
                using var taskkillProcess = Process.Start(
                    new ProcessStartInfo
                    {
                        FileName = "taskkill",
                        Arguments = $"/PID {pid} /T /F",
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                    });
                if (taskkillProcess is not null)
                {
                    taskkillProcess.WaitForExit(5000);
                }
            }
            catch
            {
                // Ignore fallback cleanup failures; the next launch can retry.
            }

            return !IsProcessAlive(pid);
        }
    }
}
