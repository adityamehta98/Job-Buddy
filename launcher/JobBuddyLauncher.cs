using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading;
using System.Windows.Forms;

internal static class JobBuddyLauncher
{
    private const string ProjectRoot = @"D:\Job-Buddy";
    private const string MutexName = "JobBuddyDesktopLauncher";

    [STAThread]
    private static void Main()
    {
        bool ownsMutex;
        using (var launcherMutex = new Mutex(true, MutexName, out ownsMutex))
        {
            if (!ownsMutex)
            {
                ShowError("Job Buddy is already open.");
                return;
            }

            Process serverProcess = null;
            try
            {
                string pythonPath = Path.Combine(ProjectRoot, @".venv\Scripts\pythonw.exe");
                string appPath = Path.Combine(ProjectRoot, "app.py");

                if (!File.Exists(pythonPath))
                    throw new FileNotFoundException("Virtual-environment Python was not found.", pythonPath);
                if (!File.Exists(appPath))
                    throw new FileNotFoundException("Job Buddy was not found.", appPath);

                string browserPath = FindBrave();
                if (browserPath == null)
                    throw new InvalidOperationException("Brave Browser is required but could not be found.");

                int port = ReadPort();
                string dashboardUrl = "http://127.0.0.1:" + port;

                if (IsDashboardReady(dashboardUrl))
                    throw new InvalidOperationException(
                        "Port " + port + " is already in use. Close the existing Job Buddy server and try again.");

                var serverStartInfo = new ProcessStartInfo
                {
                    FileName = pythonPath,
                    Arguments = Quote(appPath),
                    WorkingDirectory = ProjectRoot,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden
                };
                serverStartInfo.EnvironmentVariables["JOB_BUDDY_LAUNCHER"] = "1";
                serverProcess = Process.Start(serverStartInfo);

                if (serverProcess == null)
                    throw new InvalidOperationException("The Job Buddy server could not be started.");

                WaitForServer(serverProcess, dashboardUrl, port);

                Process.Start(new ProcessStartInfo
                {
                    FileName = browserPath,
                    Arguments = "--new-tab " + Quote(dashboardUrl),
                    UseShellExecute = false
                });

                // The page tells the managed Flask server when its normal Brave
                // tab closes. Keep this invisible launcher alive until then.
                serverProcess.WaitForExit();
            }
            catch (Exception exception)
            {
                ShowError(exception.Message);
            }
            finally
            {
                StopProcess(serverProcess);
                launcherMutex.ReleaseMutex();
            }
        }
    }

    private static void WaitForServer(Process serverProcess, string url, int port)
    {
        DateTime deadline = DateTime.UtcNow.AddSeconds(30);
        while (DateTime.UtcNow < deadline)
        {
            if (serverProcess.HasExited)
                throw new InvalidOperationException(
                    "Job Buddy could not start. Port " + port + " may already be in use.");

            if (IsDashboardReady(url))
                return;

            Thread.Sleep(250);
        }

        throw new TimeoutException("Job Buddy did not become ready within 30 seconds.");
    }

    private static bool IsDashboardReady(string url)
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "GET";
            request.Timeout = 750;
            request.ReadWriteTimeout = 750;
            request.Proxy = null;

            using (var response = (HttpWebResponse)request.GetResponse())
                return response.StatusCode == HttpStatusCode.OK;
        }
        catch
        {
            return false;
        }
    }

    private static int ReadPort()
    {
        string environmentPort = Environment.GetEnvironmentVariable("PORT");
        int parsedPort;
        if (Int32.TryParse(environmentPort, out parsedPort) && IsValidPort(parsedPort))
            return parsedPort;

        string envPath = Path.Combine(ProjectRoot, ".env");
        if (File.Exists(envPath))
        {
            foreach (string rawLine in File.ReadAllLines(envPath))
            {
                string line = rawLine.Trim();
                if (!line.StartsWith("PORT=", StringComparison.OrdinalIgnoreCase))
                    continue;

                string value = line.Substring(5).Trim().Trim('"', '\'');
                if (Int32.TryParse(value, out parsedPort) && IsValidPort(parsedPort))
                    return parsedPort;
            }
        }

        return 5000;
    }

    private static bool IsValidPort(int port)
    {
        return port >= 1 && port <= 65535;
    }

    private static string FindBrave()
    {
        string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        string programFilesX86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
        string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);

        string[] candidates =
        {
            Path.Combine(programFiles, @"BraveSoftware\Brave-Browser\Application\brave.exe"),
            Path.Combine(programFilesX86, @"BraveSoftware\Brave-Browser\Application\brave.exe"),
            Path.Combine(localAppData, @"BraveSoftware\Brave-Browser\Application\brave.exe")
        };

        foreach (string candidate in candidates)
            if (File.Exists(candidate))
                return candidate;

        return null;
    }

    private static void StopProcess(Process process)
    {
        if (process == null)
            return;

        try
        {
            if (!process.HasExited)
            {
                process.Kill();
                process.WaitForExit(5000);
            }
        }
        catch
        {
            // The process may already have exited between checks.
        }
        finally
        {
            process.Dispose();
        }
    }

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private static void ShowError(string message)
    {
        MessageBox.Show(
            message,
            "Job Buddy",
            MessageBoxButtons.OK,
            MessageBoxIcon.Error);
    }
}
