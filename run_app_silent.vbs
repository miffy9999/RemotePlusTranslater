Option Explicit
Dim fso, shell, root, pythonw, command, env
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonw) Then
  MsgBox "Run install.ps1 or install.bat first.", vbExclamation, "RemotePlus"
  WScript.Quit 1
End If
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = root
Set env = shell.Environment("PROCESS")
env("PYTHONUTF8") = "1"
env("PYGAME_HIDE_SUPPORT_PROMPT") = "1"
env("REMOTEPLUS_SILENT_LAUNCH") = "1"
env("REMOTEPLUS_DESKTOP_AUTO_SHUTDOWN") = "1"
command = Chr(34) & pythonw & Chr(34) & " -m translator_app.cli desktop"
shell.Run command, 0, False
