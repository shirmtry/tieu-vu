Set sh = CreateObject("WScript.Shell")
sh.Run "cmd /c cd /d ""__REPO__"" && "".venv\Scripts\python.exe"" main.py --no-preview", 0, False
