using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;
using Microsoft.UI.Xaml.Navigation;

namespace QbRssRulesDesktop
{
    /// <summary>
    /// Provides application-specific behavior to supplement the default Application class.
    /// </summary>
    public partial class App : Application
    {
        private const string SingleInstanceMutexName = @"Local\QbRssRulesDesktop.SingleInstance";
        private const int ActivateExistingInstanceRetryCount = 15;
        private const int ActivateExistingInstanceRetryDelayMs = 100;
        private const int SwRestore = 9;

        private static Mutex? singleInstanceMutex;
        private Window? window;
        public static Window? MainWindow { get; private set; }

        /// <summary>
        /// Initializes the singleton application object.  This is the first line of authored code
        /// executed, and as such is the logical equivalent of main() or WinMain().
        /// </summary>
        public App()
        {
            this.InitializeComponent();
        }

        /// <summary>
        /// Invoked when the application is launched normally by the end user.  Other entry points
        /// will be used such as when the application is launched to open a specific file.
        /// </summary>
        /// <param name="e">Details about the launch request and process.</param>
        protected override void OnLaunched(LaunchActivatedEventArgs e)
        {
            if (!EnsureSingleDesktopInstance())
            {
                Environment.Exit(0);
                return;
            }

            MainWindow ??= new Window();
            window = MainWindow;
            window.Title = "qB RSS Rules Desktop";

            if (window.Content is not Frame rootFrame)
            {
                rootFrame = new Frame();
                rootFrame.NavigationFailed += OnNavigationFailed;
                window.Content = rootFrame;
            }

            _ = rootFrame.Navigate(typeof(MainPage), e.Arguments);
            window.Activate();
        }

        /// <summary>
        /// Invoked when Navigation to a certain page fails
        /// </summary>
        /// <param name="sender">The Frame which failed navigation</param>
        /// <param name="e">Details about the navigation failure</param>
        void OnNavigationFailed(object sender, NavigationFailedEventArgs e)
        {
            throw new Exception("Failed to load Page " + e.SourcePageType.FullName);
        }

        private static bool EnsureSingleDesktopInstance()
        {
            if (singleInstanceMutex is not null)
            {
                return true;
            }

            var mutex = new Mutex(initiallyOwned: true, SingleInstanceMutexName, out var createdNew);
            if (createdNew)
            {
                singleInstanceMutex = mutex;
                return true;
            }

            try
            {
                TryActivateExistingInstanceWindow();
            }
            finally
            {
                mutex.Dispose();
            }

            return false;
        }

        private static void TryActivateExistingInstanceWindow()
        {
            using var currentProcess = Process.GetCurrentProcess();
            var processName = currentProcess.ProcessName;
            var currentProcessId = currentProcess.Id;

            for (var attempt = 0; attempt < ActivateExistingInstanceRetryCount; attempt++)
            {
                foreach (var process in Process.GetProcessesByName(processName))
                {
                    try
                    {
                        if (process.Id == currentProcessId)
                        {
                            continue;
                        }

                        process.Refresh();
                        var windowHandle = process.MainWindowHandle;
                        if (windowHandle == IntPtr.Zero)
                        {
                            continue;
                        }

                        ShowWindow(windowHandle, SwRestore);
                        SetForegroundWindow(windowHandle);
                        return;
                    }
                    catch
                    {
                        // Ignore races with startup/shutdown of the existing instance.
                    }
                    finally
                    {
                        process.Dispose();
                    }
                }

                Thread.Sleep(ActivateExistingInstanceRetryDelayMs);
            }

            Debug.WriteLine("Existing qB RSS Rules Desktop instance was detected but no window handle was available to foreground.");
        }

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    }
}
