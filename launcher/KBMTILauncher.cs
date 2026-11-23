using System;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace KBMTI.Launcher
{
    internal static class Program
    {
        private const string BatchName = "x.bat";

        private static int Fail(string message)
        {
            Console.Error.WriteLine("[KBMTI] " + message);
            return 2;
        }

        private static string Sha256(string path)
        {
            using (var sha = SHA256.Create())
            using (var stream = File.OpenRead(path))
            {
                byte[] hash = sha.ComputeHash(stream);
                var builder = new StringBuilder(hash.Length * 2);
                foreach (byte value in hash)
                {
                    builder.Append(value.ToString("x2"));
                }
                return builder.ToString();
            }
        }

        public static int Main(string[] args)
        {
            Console.OutputEncoding = Encoding.UTF8;
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string bat = Path.Combine(baseDir, BatchName);
            if (!File.Exists(bat))
            {
                return Fail("The official x.bat launcher is missing next to the executable.");
            }

            string actual;
            try
            {
                actual = Sha256(bat);
            }
            catch (Exception exc)
            {
                return Fail("Could not read x.bat: " + exc.Message);
            }
            if (!string.Equals(actual, LauncherIntegrity.XBatSha256, StringComparison.OrdinalIgnoreCase))
            {
                return Fail("The launcher source failed its integrity check. Rebuild KBMTI-RAW-TEST.exe.");
            }

            bool skip = false;
            bool selfTest = false;
            foreach (string arg in args)
            {
                if (string.Equals(arg, "/skip", StringComparison.OrdinalIgnoreCase))
                {
                    skip = true;
                }
                else if (string.Equals(arg, "/selftest", StringComparison.OrdinalIgnoreCase))
                {
                    selfTest = true;
                }
            }

            string extra = selfTest ? " /selftest" : (skip ? " /skip" : string.Empty);
            // The working directory is the install folder, so cmd can resolve
            // x.bat without embedding a quoted absolute path.
            var start = new ProcessStartInfo
            {
                FileName = Path.Combine(Environment.SystemDirectory, "cmd.exe"),
                Arguments = "/d /s /c x.bat" + extra,
                WorkingDirectory = baseDir,
                UseShellExecute = false,
                CreateNoWindow = false,
            };
            try
            {
                using (Process child = Process.Start(start))
                {
                    if (child == null)
                    {
                        return Fail("Windows could not start the official launcher.");
                    }
                    child.WaitForExit();
                    return child.ExitCode;
                }
            }
            catch (Exception exc)
            {
                return Fail("The official launcher could not start: " + exc.Message);
            }
        }
    }
}
