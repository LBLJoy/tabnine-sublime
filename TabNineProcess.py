import os
import sublime
import subprocess
import json
import stat

from package_control import package_manager

SETTINGS_PATH = 'TabNine.sublime-settings'
PACK_MANAGER = package_manager.PackageManager()
MAX_RESTARTS = 10

def add_execute_permission(path):
    st = os.stat(path)
    new_mode = st.st_mode | stat.S_IEXEC
    if new_mode != st.st_mode:
        os.chmod(path, new_mode)

def get_startup_info(platform):
    if platform == "windows":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return si
    else:
        return None

def parse_semver(s):
    try:
        return [int(x) for x in s.split('.')]
    except ValueError:
        return []

def get_tabnine_path(binary_dir):
    def join_path(*args):
        return os.path.join(binary_dir, *args)
    translation = {
        ("linux", "x32"): "i686-unknown-linux-musl/TabNine",
        ("linux", "x64"): "x86_64-unknown-linux-musl/TabNine",
        ("osx", "x32"): "i686-apple-darwin/TabNine",
        ("osx", "x64"): "x86_64-apple-darwin/TabNine",
        ("windows", "x32"): "i686-pc-windows-gnu/TabNine.exe",
        ("windows", "x64"): "x86_64-pc-windows-gnu/TabNine.exe",
    }
    versions = os.listdir(binary_dir)
    versions.sort(key=parse_semver, reverse=True)
    for version in versions:
        key = sublime.platform(), sublime.arch()
        path = join_path(version, translation[key])
        if os.path.isfile(path):
            add_execute_permission(path)
            print("TabNine: starting version", version)
            return path


class TabNineProcess:
    install_directory = os.path.dirname(os.path.realpath(__file__))
    def __init__(self):
        self.tabnine_proc = None
        self.num_restarts = 0

        def on_change():
            self.num_restarts = 0
            self.restart_tabnine_proc()
        sublime.load_settings(SETTINGS_PATH).add_on_change('TabNine', on_change)

    @staticmethod
    def run_tabnine(inheritStdio=False, additionalArgs=[]):
        binary_dir = os.path.join(TabNineProcess.install_directory, "binaries")
        settings = sublime.load_settings(SETTINGS_PATH)
        tabnine_path = settings.get("custom_binary_path")
        if tabnine_path is None:
            tabnine_path = get_tabnine_path(binary_dir)
        args = [tabnine_path, "--client", "sublime"] + additionalArgs
        log_file_path = settings.get("log_file_path")
        if log_file_path is not None:
            args += ["--log-file-path", log_file_path]
        extra_args = settings.get("extra_args")
        if extra_args is not None:
            args += extra_args
        plugin_version = PACK_MANAGER.get_metadata("TabNine").get('version')
        if not plugin_version:
            plugin_version = "Unknown"
        sublime_version = sublime.version()
        args += ["--client-metadata", "clientVersion=" + sublime_version, "clientApiVersion=" + sublime_version, "pluginVersion=" + plugin_version]
        return subprocess.Popen(
            args,
            stdin=None if inheritStdio else subprocess.PIPE,
            stdout=None if inheritStdio else subprocess.PIPE,
            stderr=subprocess.STDOUT,
            startupinfo=get_startup_info(sublime.platform()))

    def restart_tabnine_proc(self):
        if self.tabnine_proc is not None:
            try:
                self.tabnine_proc.terminate()
            except Exception: #pylint: disable=W0703
                pass
        self.tabnine_proc = TabNineProcess.run_tabnine()

    def request(self, req):
        if self.tabnine_proc is None:
            self.restart_tabnine_proc()
        if self.tabnine_proc.poll():
            print("TabNine subprocess is dead")
            if self.num_restarts < MAX_RESTARTS:
                print("Restarting it...")
                self.num_restarts += 1
                self.restart_tabnine_proc()
            else:
                return None
        req = {
            "version": "2.0.0",
            "request": req
        }
        req = json.dumps(req)
        req += '\n'
        try:
            self.tabnine_proc.stdin.write(bytes(req, "UTF-8"))
            self.tabnine_proc.stdin.flush()
            result = self.tabnine_proc.stdout.readline()
            result = str(result, "UTF-8")
            result = json.loads(result)
            return result
        except (IOError, OSError, UnicodeDecodeError, ValueError) as e:
            print("Exception while interacting with TabNine subprocess:", e)
            if self.num_restarts < MAX_RESTARTS:
                self.num_restarts += 1
                self.restart_tabnine_proc()


tabnine_proc = TabNineProcess()