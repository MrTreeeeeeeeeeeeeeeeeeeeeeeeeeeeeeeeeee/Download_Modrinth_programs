Option Explicit
Dim shell, files, folder, launcher, candidates, candidate, command, code
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
launcher = files.BuildPath(folder, "Downloader.pyw")
candidates = Array("pythonw.exe", "pyw.exe")
For Each candidate In candidates
    On Error Resume Next
    Err.Clear
    command = candidate & " " & Chr(34) & launcher & Chr(34)
    code = shell.Run(command, 0, False)
    If Err.Number = 0 Then
        On Error GoTo 0
        WScript.Quit
    End If
    On Error GoTo 0
Next
MsgBox "Python 3.10 or newer is required. Install Python from python.org with 'Add Python to PATH' selected, then open this file again.", 48, "Modrinth Downloader"
