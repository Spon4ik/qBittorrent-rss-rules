using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Text.Json;
using System.Text.RegularExpressions;
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
        private static readonly string[] RequiredDesktopBackendCapabilities =
        {
            "hover_debug_telemetry",
            "search_hidden_result_diagnostics",
            "jellyfin_auto_sync",
            "stremio_library_sync",
        };

        private const string DefaultBackendUrl = "http://127.0.0.1:8000";
        private const string RequiredDesktopBackendContract = "2026-04-18";
        private const string RequiredDesktopBackendAppVersion = "1.1.2";
        private const string ManagedBackendStateFileName = "desktop-managed-backend.json";
        private const int ManagedBackendPortSearchLimit = 32;
        private const int ReconnectAttemptLimit = 30;
        private static readonly Regex MultiprocessingParentPidRegex = new(@"spawn_main\(parent_pid=(\d+),", RegexOptions.Compiled | RegexOptions.IgnoreCase);
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
        private bool backendVersionMismatchDetected;
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
        private sealed record PythonProcessInfo(int ProcessId, int ParentProcessId, string CommandLine);

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
                : backendVersionMismatchDetected
                    ? "Run scripts\\run_dev.bat desktop to rebuild and relaunch the desktop shell so it matches the current backend."
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
            backendVersionMismatchDetected = false;
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
                    backendVersionMismatchDetected = true;
                    lastBackendProbeFailure = string.IsNullOrWhiteSpace(appVersion)
                        ? $"An incompatible backend is already listening at {backendUri}; expected app version {RequiredDesktopBackendAppVersion}."
                        : $"An incompatible backend is already listening at {backendUri}; expected app version {RequiredDesktopBackendAppVersion}, got {appVersion}. The desktop shell is older than the running backend.";
                    return false;
                }

                var missingCapabilities = MissingRequiredCapabilities(root);
                if (missingCapabilities.Length > 0)
                {
                    lastBackendProbeFailure =
                        $"An incompatible backend is already listening at {backendUri}; missing required desktop capabilities: {string.Join(", ", missingCapabilities)}.";
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

        private static string[] MissingRequiredCapabilities(JsonElement healthPayload)
        {
            if (!healthPayload.TryGetProperty("capabilities", out var capabilitiesElement)
                || capabilitiesElement.ValueKind != JsonValueKind.Array)
            {
                return RequiredDesktopBackendCapabilities;
            }

            var availableCapabilities = capabilitiesElement
                .EnumerateArray()
                .Select(value => value.GetString())
                .Where(value => !string.IsNullOrWhiteSpace(value))
                .Cast<string>()
                .ToHashSet(StringComparer.Ordinal);

            return RequiredDesktopBackendCapabilities
                .Where(capability => !availableCapabilities.Contains(capability))
                .ToArray();
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

        private bool HasControllableActiveBackend()
        {
            return CollectControllableLocalBackendPids(includeCurrentPort: true).Count > 0;
        }

        private bool StopActiveBackendProcess()
        {
            return StopControllableLocalBackends();
        }

        private void OnStartBackendClicked(object sender, RoutedEventArgs e)
        {
            _ = TryStartBackendProcess(autoTriggered: false);
        }

        private void OnShutdownEngineClicked(object sender, RoutedEventArgs e)
        {
            reconnectTimer.Stop();
            localChangeDebounceTimer.Stop();
            if (!HasControllableActiveBackend())
            {
                ConnectionStatusText.Text = "Backend is not running";
                if (OfflinePanel.Visibility == Visibility.Visible)
                {
                    OfflineMessageText.Text = "No controllable local backend is currently running for this desktop session.";
                }
                return;
            }

            if (StopActiveBackendProcess())
            {
                ShowOfflineState("Backend shut down. Use Start Backend to launch it again.");
                return;
            }

            ShowOfflineState(
                "Backend shutdown could not be confirmed yet. If a stale loopback backend is still running, retry once more or restart the desktop app so it can reconnect to the current engine."
            );
        }

        private void OnRestartBackendClicked(object sender, RoutedEventArgs e)
        {
            reconnectTimer.Stop();
            localChangeDebounceTimer.Stop();

            if (HasControllableActiveBackend() && !StopActiveBackendProcess())
            {
                ShowOfflineState(
                    "Backend restart could not stop the current controllable local backend yet. Retry once more or restart the desktop app so it can reconnect to the current engine."
                );
                return;
            }

            ConnectionStatusText.Text = "Restarting backend...";
            OfflineMessageText.Text = $"Restarting the local backend at {backendUri}.";
            OfflinePanel.Visibility = Visibility.Visible;
            AppWebView.Visibility = Visibility.Collapsed;
            _ = TryStartBackendProcess(autoTriggered: false);
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

            if (TryStopKnownLocalBackendOnPort(backendUri.Port) && IsLoopbackPortAvailable(backendUri.Port))
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

        private int? ResolveCurrentBackendPid()
        {
            if (usesConfiguredBackendUrl || !backendUri.IsLoopback)
            {
                return null;
            }

            return ResolveListeningProcessId(backendUri.Port);
        }

        private int[] ControllableLocalBackendPorts(bool includeCurrentPort)
        {
            if (usesConfiguredBackendUrl || !backendUri.IsLoopback)
            {
                return [];
            }

            var defaultPort = new Uri(DefaultBackendUrl).Port;
            var startPort = Math.Min(defaultPort, backendUri.Port);
            var endExclusive = Math.Max(defaultPort + ManagedBackendPortSearchLimit, backendUri.Port + 1);
            var ports = new HashSet<int>();
            for (var port = startPort; port < endExclusive; port++)
            {
                ports.Add(port);
            }

            if (includeCurrentPort)
            {
                ports.Add(backendUri.Port);
            }

            return ports
                .Where(port => includeCurrentPort || port != backendUri.Port)
                .OrderBy(port => port)
                .ToArray();
        }

        private HashSet<int> CollectControllableLocalBackendPids(bool includeCurrentPort)
        {
            var backendPids = new HashSet<int>();
            if (managedBackendProcess is { HasExited: false })
            {
                backendPids.Add(managedBackendProcess.Id);
            }

            var candidatePorts = ControllableLocalBackendPorts(includeCurrentPort);
            if (candidatePorts.Length == 0)
            {
                return backendPids;
            }

            var listeningProcessIds = ResolveListeningProcessIds(candidatePorts);
            foreach (var port in candidatePorts)
            {
                if (!listeningProcessIds.TryGetValue(port, out var pid) || pid <= 0)
                {
                    continue;
                }

                if (!IsQbRssDesktopBackend(BuildLoopbackBackendUri(port)))
                {
                    continue;
                }

                backendPids.Add(pid);
            }

            foreach (var pid in CollectAssociatedPythonWorkerPids(backendPids))
            {
                backendPids.Add(pid);
            }

            return backendPids;
        }

        private bool StopControllableLocalBackends()
        {
            var backendPids = CollectControllableLocalBackendPids(includeCurrentPort: true);
            if (backendPids.Count == 0)
            {
                return false;
            }
            var stopped = KillProcessSet(backendPids);

            try
            {
                if (managedBackendProcess is not null)
                {
                    managedBackendProcess.Dispose();
                    managedBackendProcess = null;
                }
            }
            catch
            {
                managedBackendProcess = null;
            }

            DeleteManagedBackendState(force: true);
            return stopped;
        }

        private bool TryStopKnownLocalBackendOnPort(int port)
        {
            if (usesConfiguredBackendUrl || port <= 0)
            {
                return false;
            }

            var listeningProcessIds = ResolveListeningProcessIds([port]);
            if (!listeningProcessIds.TryGetValue(port, out var pid) || pid <= 0)
            {
                return false;
            }

            if (!IsQbRssDesktopBackend(BuildLoopbackBackendUri(port)))
            {
                return false;
            }

            var candidatePids = new HashSet<int> { pid };
            foreach (var workerPid in CollectAssociatedPythonWorkerPids(candidatePids))
            {
                candidatePids.Add(workerPid);
            }

            return KillProcessSet(candidatePids);
        }

        private static HashSet<int> CollectAssociatedPythonWorkerPids(IEnumerable<int> rootPids)
        {
            var knownRootPids = rootPids.Where(pid => pid > 0).ToHashSet();
            if (knownRootPids.Count == 0)
            {
                return [];
            }

            var associatedPids = new HashSet<int>();
            var pythonProcesses = QueryPythonProcesses();
            var expanded = true;
            while (expanded)
            {
                expanded = false;
                foreach (var process in pythonProcesses)
                {
                    if (process.ProcessId <= 0 || knownRootPids.Contains(process.ProcessId) || associatedPids.Contains(process.ProcessId))
                    {
                        continue;
                    }

                    var referencedParentPid = ReferencedMultiprocessingParentPid(process.CommandLine);
                    if (!knownRootPids.Contains(process.ParentProcessId)
                        && (referencedParentPid is null || !knownRootPids.Contains(referencedParentPid.Value))
                        && !associatedPids.Contains(process.ParentProcessId)
                        && (referencedParentPid is null || !associatedPids.Contains(referencedParentPid.Value)))
                    {
                        continue;
                    }

                    associatedPids.Add(process.ProcessId);
                    expanded = true;
                }
            }

            return associatedPids;
        }

        private static int? ReferencedMultiprocessingParentPid(string? commandLine)
        {
            if (string.IsNullOrWhiteSpace(commandLine))
            {
                return null;
            }

            var match = MultiprocessingParentPidRegex.Match(commandLine);
            if (!match.Success)
            {
                return null;
            }

            return int.TryParse(match.Groups[1].Value, out var pid) && pid > 0 ? pid : null;
        }

        private static IReadOnlyList<PythonProcessInfo> QueryPythonProcesses()
        {
            try
            {
                using var process = Process.Start(
                    new ProcessStartInfo
                    {
                        FileName = "powershell",
                        Arguments = "-NoProfile -Command \"Get-CimInstance Win32_Process -Filter \\\"name = 'python.exe'\\\" | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress\"",
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                    });
                if (process is null)
                {
                    return [];
                }

                var output = process.StandardOutput.ReadToEnd().Trim();
                process.WaitForExit(5000);
                if (string.IsNullOrWhiteSpace(output))
                {
                    return [];
                }

                using var payload = JsonDocument.Parse(output);
                if (payload.RootElement.ValueKind == JsonValueKind.Array)
                {
                    return payload.RootElement
                        .EnumerateArray()
                        .Select(ParsePythonProcessInfo)
                        .Where(info => info is not null)
                        .Cast<PythonProcessInfo>()
                        .ToArray();
                }

                var single = ParsePythonProcessInfo(payload.RootElement);
                return single is null ? [] : [single];
            }
            catch
            {
                return [];
            }
        }

        private static PythonProcessInfo? ParsePythonProcessInfo(JsonElement element)
        {
            if (!element.TryGetProperty("ProcessId", out var processIdElement)
                || !element.TryGetProperty("ParentProcessId", out var parentProcessIdElement))
            {
                return null;
            }

            var processId = processIdElement.GetInt32();
            var parentProcessId = parentProcessIdElement.GetInt32();
            var commandLine = element.TryGetProperty("CommandLine", out var commandLineElement)
                ? commandLineElement.GetString() ?? ""
                : "";
            if (processId <= 0)
            {
                return null;
            }

            return new PythonProcessInfo(processId, parentProcessId, commandLine);
        }

        private static bool KillProcessSet(IEnumerable<int> pids)
        {
            var processIds = pids.Where(pid => pid > 0).Distinct().ToArray();
            if (processIds.Length == 0)
            {
                return false;
            }

            var allStopped = true;
            foreach (var pid in processIds)
            {
                if (!TryKillProcessTree(pid) && IsProcessAlive(pid))
                {
                    allStopped = false;
                }
            }

            return allStopped || processIds.All(pid => !IsProcessAlive(pid));
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
            StopControllableLocalBackends();
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

        private static int? ResolveListeningProcessId(int port)
        {
            var listeningProcessIds = ResolveListeningProcessIds([port]);
            return listeningProcessIds.TryGetValue(port, out var pid) ? pid : null;
        }

        private static Dictionary<int, int> ResolveListeningProcessIds(IEnumerable<int> ports)
        {
            var requestedPorts = ports
                .Where(port => port > 0)
                .Distinct()
                .ToHashSet();
            var listeningProcessIds = new Dictionary<int, int>();
            if (requestedPorts.Count == 0)
            {
                return listeningProcessIds;
            }

            try
            {
                using var netstatProcess = Process.Start(
                    new ProcessStartInfo
                    {
                        FileName = "netstat",
                        Arguments = "-ano -p tcp",
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                    });
                if (netstatProcess is null)
                {
                    return listeningProcessIds;
                }

                var output = netstatProcess.StandardOutput.ReadToEnd();
                netstatProcess.WaitForExit(5000);
                foreach (var rawLine in output.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries))
                {
                    var line = rawLine.Trim();
                    if (!line.StartsWith("TCP", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    var columns = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                    if (columns.Length < 5 || !string.Equals(columns[3], "LISTENING", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    if (!TryParseEndpointPort(columns[1], out var endpointPort) || !requestedPorts.Contains(endpointPort))
                    {
                        continue;
                    }

                    if (int.TryParse(columns[4], out var pid) && pid > 0)
                    {
                        listeningProcessIds[endpointPort] = pid;
                    }
                }

                return listeningProcessIds;
            }
            catch
            {
                return listeningProcessIds;
            }
        }

        private static bool TryParseEndpointPort(string endpoint, out int port)
        {
            port = 0;
            var separatorIndex = endpoint.LastIndexOf(':');
            if (separatorIndex < 0 || separatorIndex >= endpoint.Length - 1)
            {
                return false;
            }

            return int.TryParse(endpoint[(separatorIndex + 1)..], out port) && port > 0;
        }

        private static bool EndpointMatchesPort(string endpoint, int port)
        {
            return TryParseEndpointPort(endpoint, out var endpointPort) && endpointPort == port;
        }

        private static Uri BuildLoopbackBackendUri(int port)
        {
            return new Uri($"http://127.0.0.1:{port}/");
        }

        private static bool IsQbRssDesktopBackend(Uri backendBaseUri)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, new Uri(backendBaseUri, "/health"));
                using var response = BackendProbeClient.SendAsync(request).GetAwaiter().GetResult();
                if (!response.IsSuccessStatusCode)
                {
                    return false;
                }

                using var payload = JsonDocument.Parse(response.Content.ReadAsStringAsync().GetAwaiter().GetResult());
                var root = payload.RootElement;
                var status = root.TryGetProperty("status", out var statusElement) ? statusElement.GetString() : "";
                var contract = root.TryGetProperty("desktop_backend_contract", out var contractElement)
                    ? contractElement.GetString()
                    : "";
                return string.Equals(status, "ok", StringComparison.OrdinalIgnoreCase)
                    && !string.IsNullOrWhiteSpace(contract);
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
