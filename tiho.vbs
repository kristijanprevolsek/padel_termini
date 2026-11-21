' Pokrece provjera.bat (ili bat zadan kao argument) bez crnog prozora.
Set sh = CreateObject("WScript.Shell")
dir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
bat = "provjera.bat"
If WScript.Arguments.Count > 0 Then bat = WScript.Arguments(0)
sh.Run """" & dir & "\" & bat & """", 0, False
