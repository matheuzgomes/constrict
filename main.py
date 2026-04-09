import os
import sys
import stat
import os.path
from functools import lru_cache
from collections import deque
from contextlib import redirect_stdout, redirect_stderr
from typing import Callable

def _get_shlex_split():
    import shlex
    return shlex.split

def _get_subprocess_run():
    import subprocess
    return subprocess.run


@lru_cache(maxsize=64)
def _exec_path(command: str) -> str | None:
    """Returns string path, not Path object."""
    for p in os.getenv("PATH", "").split(os.pathsep):
        file_path = os.path.join(p, command)
        try:
            if os.stat(file_path).st_mode & stat.S_IXUSR:
                return file_path
        except (FileNotFoundError, PermissionError):
            continue
    return None


class ShellState:
    """Plain class with __slots__ is smaller and faster than dataclass(slots=True)."""
    __slots__ = (
        'oldpwd', 'cpwd', 'history', 'builtin_commands',
        'redirection_standards', 'redirect_types', 'is_running', 'redirect_keys_sorted'
    )

    def __init__(self):
        self.oldpwd: str | None = None
        self.cpwd: str | None = None
        self.history: deque[str] = deque(maxlen=100)
        self.builtin_commands: dict[str, Callable] = {}
        self.redirection_standards: dict[str, Callable] = {
            "stdout": redirect_stdout,
            "stderr": redirect_stderr,
        }
        self.redirect_types: dict[str, tuple[str, str]] = {
            ">": ("stdout", "w"), "1>": ("stdout", "w"),
            ">>": ("stdout", "a"), "1>>": ("stdout", "a"),
            "2>": ("stderr", "w"), "2>>": ("stderr", "a"),
        }
        self.redirect_keys_sorted = sorted(self.redirect_types.keys(), key=len, reverse=True)
        self.is_running: bool = True


class Completer:
    def __init__(self, commands: dict[str, Callable]):
        self._commands = commands
        self._matches: list[str] = []
        self._executables: list[str] | None = None
        self._loaded: bool = False

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load_executables()
            self._loaded = True

    def _load_executables(self) -> None:
        uid = os.getuid()
        gids = set(os.getgroups())
        exes: list[str] = []
        seen: set[str] = set()

        for p in os.getenv("PATH", "").split(os.pathsep):
            try:
                with os.scandir(p) as it:
                    for ent in it:
                        name = ent.name
                        if name in seen or not ent.is_file(follow_symlinks=False):
                            continue
                        st = ent.stat(follow_symlinks=False)
                        mode = st.st_mode
                        if ((st.st_uid == uid and mode & stat.S_IXUSR) or
                            (st.st_gid in gids and mode & stat.S_IXGRP) or
                            (mode & stat.S_IXOTH)):
                            seen.add(name)
                            exes.append(name)
            except OSError:
                continue
        self._executables = sorted(exes)

    def complete(self, text: str, state: int) -> str | None:
        if state == 0:
            import readline
            begidx = readline.get_begidx()
            is_argument = begidx > 0 or "/" in text or text.startswith("~")

            candidates: list[str] = []
            if is_argument:
                candidates = self._path_candidates(text)
            else:
                candidates = [cmd for cmd in self._commands if cmd.startswith(text)]
                self._ensure_loaded()
                if self._executables:
                    candidates.extend(exe for exe in self._executables if exe.startswith(text))

            self._matches = sorted(set(candidates))

        try:
            match = self._matches[state]
        except IndexError:
            return None

        return match + " " if len(self._matches) == 1 and not match.endswith("/") else match

    def _path_candidates(self, text: str) -> list[str]:
        expanded = os.path.expanduser(text)
        dirname = os.path.dirname(expanded) or "."
        prefix = os.path.basename(expanded)
        try:
            entries = []
            with os.scandir(dirname) as it:
                for ent in it:
                    if prefix and not ent.name.startswith(prefix):
                        continue
                    full = os.path.join(dirname, ent.name)
                    if ent.is_dir():
                        entries.append(full + "/")
                    else:
                        entries.append(full + " ")
            return entries
        except OSError:
            return []

    def install(self) -> None:
        import readline
        readline.parse_and_bind("tab: complete")
        readline.set_completer(self.complete)
        readline.set_completer_delims(" \t\n")


class HistoryWriter:
    __slots__ = ('_path', '_buffer', '_buffer_size', '_file')
    
    def __init__(self, path: str, buffer_size: int = 10):
        self._path = path
        self._buffer: list[str] = []
        self._buffer_size = buffer_size
        self._file = None

    def append(self, entry: str) -> None:
        self._buffer.append(entry)
        if len(self._buffer) >= self._buffer_size:
            self._flush()

    def _flush(self) -> None:
        if self._buffer and self._file:
            self._file.write("".join(f"{line}\n" for line in self._buffer))
            self._buffer.clear()

    def close(self) -> None:
        self._flush()
        if self._file:
            self._file.close()

    def __enter__(self): 
        self._file = open(self._path, "a", buffering=1, encoding="utf-8")
        return self
    
    def __exit__(self, *args): 
        self.close()


class Builtins:
    __slots__ = ('state',)
    
    def __init__(self, state: ShellState):
        self.state = state

    def echo(self, args: list[str]) -> None:
        if args:
            sys.stdout.write(" ".join(args) + "\n")

    def type(self, args: list[str]) -> None:
        if not args: return
        cmd = args[0]
        if self.state.builtin_commands.get(cmd):
            sys.stdout.write(f"{cmd} is a shell builtin\n")
            return
        fp = _exec_path(cmd)
        sys.stdout.write(f"{cmd} is {fp}\n" if fp else f"{cmd}: not found\n")

    def pwd(self, _args: list[str]) -> None:
        sys.stdout.write(os.getcwd() + "\n")

    def cd(self, args: list[str]) -> None:
        raw = " ".join(args).strip() or os.path.expanduser("~")
        
        if raw == "-":
            if not self.state.oldpwd: return
            target_path = self.state.oldpwd
        else:
            target_path = os.path.expanduser(raw)

        if not os.path.isdir(target_path):
            sys.stdout.write(f"cd: not a directory: {target_path}\n")
            return
        if not os.access(target_path, os.X_OK):
            sys.stdout.write(f"cd: {target_path}: Permission denied\n")
            return

        current = os.path.abspath(os.getcwd())
        dest = os.path.abspath(target_path)
        if current == dest: return

        self.state.oldpwd = current
        os.chdir(target_path)

        cwd = os.path.abspath(os.getcwd())
        home = os.path.abspath(os.path.expanduser("~"))
        if cwd.startswith(home):
            rel = cwd[len(home):].lstrip("/")
            self.state.cpwd = "~" if not rel else f"~/{rel}"
        else:
            self.state.cpwd = cwd

    def history(self, args: list[str]) -> None:
        try:
            start = int(args[0]) if args else 0
        except ValueError:
            sys.stdout.write("history: invalid argument\n")
            return
        entries = list(enumerate(self.state.history, start=1))
        if start > 0: entries = entries[-start:]
        for count, entry in entries:
            sys.stdout.write(f"{count:>5} {entry}\n")

    def exit(self, _args: list[str]) -> None:
        sys.exit()


class Resolver:
    __slots__ = ('state',)
    
    def __init__(self, state: ShellState):
        self.state = state

    def extract_redirect(self, tokens: list[str]) -> tuple[list[str], str | None, str | None, str | None]:
        for key in self.state.redirect_keys_sorted:
            if key in tokens:
                i = tokens.index(key)
                if i + 1 >= len(tokens):
                    sys.stderr.write(f"syntax error: no target for {key}\n")
                    return tokens, None, None, None
                stream_name, mode = self.state.redirect_types[key]
                return tokens[:i], os.path.expanduser(tokens[i + 1]), mode, stream_name
        return tokens, None, None, None

    def resolve_command(self, tokens: list[str]) -> tuple[str, list[str], Callable | None]:
        return tokens[0], tokens[1:], self.state.builtin_commands.get(tokens[0])


class Dispatcher:
    def handle_executable(self, command: str, args: list[str], redirect_path: str | None, 
                          mode: str | None, stream_name: str | None) -> bool:
        exec_path = _exec_path(command)
        if not exec_path: return False

        run = _get_subprocess_run()
        argv = [exec_path] + args
        
        if not redirect_path:
            run(argv)
        else:
            with open(redirect_path, mode) as f:
                run(argv, **({"stderr": f} if stream_name == "stderr" else {"stdout": f}))
        return True


class Shell:
    HISTORY_PATH: str = os.path.join(os.path.expanduser("~"), ".constrict_history")

    def __init__(self):
        self.state = ShellState()
        self.builtins = Builtins(self.state)
        self.resolver = Resolver(self.state)
        self.dispatcher = Dispatcher()

        self.state.builtin_commands = {
            "echo": self.builtins.echo, "type": self.builtins.type,
            "exit": self.builtins.exit, "pwd": self.builtins.pwd,
            "cd": self.builtins.cd, "history": self.builtins.history,
        }

        self._load_history()
        self.completer = Completer(self.state.builtin_commands)
        self.completer.install()

    def _load_history(self) -> None:
        import readline
        try:
            with open(self.HISTORY_PATH, "r", encoding="utf-8") as f:
                for line in f.readlines()[-100:]:
                    entry = line.rstrip("\n")
                    self.state.history.append(entry)
                    readline.add_history(entry)
            readline.set_history_length(100)
        except FileNotFoundError:
            pass

    def run(self) -> None:
        import readline
        split = _get_shlex_split()
        
        with HistoryWriter(self.HISTORY_PATH) as writer:
            while self.state.is_running:
                try:
                    user_input = input(f"{self.state.cpwd or '~'}\n$ ")
                    if not user_input: continue

                    self.state.history.append(user_input)
                    readline.add_history(user_input)
                    writer.append(user_input)

                    tokens = split(user_input)
                    if not tokens: continue

                    tokens, redir_path, mode, stream = self.resolver.extract_redirect(tokens)
                    cmd, args, builtin = self.resolver.resolve_command(tokens)

                    if builtin:
                        if not redir_path:
                            builtin(args)
                        else:
                            redirector = self.state.redirection_standards.get(stream)
                            with open(redir_path, mode) as f:
                                with redirector(f): builtin(args)
                    elif not self.dispatcher.handle_executable(cmd, args, redir_path, mode, stream):
                        sys.stdout.write(f"{cmd}: not found\n")

                except KeyboardInterrupt:
                    sys.stdout.write("\n")
                    return
                except EOFError:
                    return

if __name__ == "__main__":
    Shell().run()