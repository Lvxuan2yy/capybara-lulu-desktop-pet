' 水豚噜噜桌宠启动器（无控制台黑窗）
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("Wscript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = "D:\python\pythonw.exe"
If Not fso.FileExists(pythonw) Then
    MsgBox "Python not found: " & pythonw & "  Please install Python 3.10+ and PySide6.", 16, "LuluPet"
    WScript.Quit
End If
ws.CurrentDirectory = scriptDir
ws.Run """" & pythonw & """ """ & scriptDir & "\lulu_pet.py""", 0, False