// Lanzador de Herramienta Tango: un .exe chico que abre el programa con el Python oficial que
// viene en la misma carpeta (python\pythonw.exe app\HerramientaTango.pyw). Hace lo mismo que
// "Abrir Herramienta Tango.cmd", pero con icono y como cualquier aplicacion de Windows.
// No trae Python adentro (a diferencia de los .exe de PyInstaller, que el antivirus marcaba).
// Se compila en GitHub Actions con el csc de .NET Framework (ver scripts/armar_paquete.ps1).
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("Herramienta Tango")]
[assembly: System.Reflection.AssemblyProduct("Herramienta Tango")]
[assembly: System.Reflection.AssemblyCompany("Sianco")]
[assembly: System.Reflection.AssemblyDescription("Abre Herramienta Tango")]

static class Lanzador
{
    [STAThread]
    static int Main(string[] args)
    {
        string carpeta = AppDomain.CurrentDomain.BaseDirectory;
        string pythonw = Path.Combine(carpeta, "python", "pythonw.exe");
        string programa = Path.Combine(carpeta, "app", "HerramientaTango.pyw");
        if (!File.Exists(pythonw) || !File.Exists(programa))
        {
            MessageBox.Show("No se encontró el programa al lado de este archivo.\n\n" +
                            "Descomprimí todo el zip HerramientaTango en una carpeta y abrí este archivo desde ahí " +
                            "(no desde adentro del zip).", "Herramienta Tango", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
        var inicio = new ProcessStartInfo(pythonw)
        {
            Arguments = string.Join(" ", new[] { Comillas(programa) }.Concat(args.Select(Comillas))),
            WorkingDirectory = carpeta,
            UseShellExecute = false,
        };
        try
        {
            var p = Process.Start(inicio);
            // Con argumentos (por ejemplo en las pruebas) espera y devuelve el resultado del programa
            if (args.Length > 0 && p != null) { p.WaitForExit(); return p.ExitCode; }
            return 0;
        }
        catch (Exception e)
        {
            MessageBox.Show("No se pudo abrir Herramienta Tango: " + e.Message, "Herramienta Tango",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    static string Comillas(string s) { return "\"" + s.Replace("\"", "\\\"") + "\""; }
}
