<div align="center">

<h1>🐍 Constrict</h1>

<pre>
 ________  ________  ________   ________  _________  ________  ___  ________ _________   
|\   ____\|\   __  \|\   ___  \|\   ____\|\___   ___\\   __  \|\  \|\   ____\\___   ___\ 
\ \  \___|\ \  \|\  \ \  \\ \  \ \  \___|\|___ \  \_\ \  \|\  \ \  \ \  \___\|___ \  \_| 
 \ \  \    \ \  \\\  \ \  \\ \  \ \_____  \   \ \  \ \ \   _  _\ \  \ \  \       \ \  \  
  \ \  \____\ \  \\\  \ \  \\ \  \|____|\  \   \ \  \ \ \  \\  \\ \  \ \  \____   \ \  \ 
   \ \_______\ \_______\ \__\\ \__\____\_\  \   \ \__\ \ \__\\ _\\ \__\ \_______\  \ \__\
    \|_______|\|_______|\|__| \|__|\_________\   \|__|  \|__|\|__|\|__|\|_______|   \|__|
                                  \|_________|                                           
</pre>

<i>A Python shell that tries really hard not to be slow.</i>

</div>

---

### So, what is this?

I started playing around with the idea of building a terminal in pure Python, but I quickly realized how easy it is to write Python code that eats up a ton of memory for no reason.

`Constrict` is the result of me trying to squeeze the absolute maximum performance out of a Python interpreter. It ditched the standard, comfortable Python modules for the bare-metal C-level stuff. It sits at around **14 MB of actual RAM**, which is pretty much the floor for anything using Python + GNU Readline.

### What can it do?

It handles the basics you'd expect from a basic shell:

* **Tab completion** (but it lazily scans your `$PATH` in the background so it doesn't slow down startup)
* **Command history** (buffers writes to disk so it doesn't spam your hard drive)
* **Redirections** (`>`, `>>`, `1>`, `2>`, etc.)
* **Built-ins** like `cd`, `echo`, `pwd`, `type`, and `history`
* **Runs actual programs** — it's not just an echo chamber for built-ins. You can run `ls`, `grep`, `bat`, or whatever else is sitting in your `$PATH`.

### Running it

It doesn't need any crazy dependencies, just Python 3.12+ (I currently test it on 3.14).

```bash
git clone https://github.com/YOUR_USERNAME/constrict-shell.git
cd constrict-shell
python3 main.py
```

### Compiling it (Optional)

Because the code avoids a lot of Python's heavy magic, it compiles beautifully with [Nuitka](https://nuitka.net/) into a standalone binary.

```bash
pip install nuitka
# Make sure you have a C compiler installed (gcc, etc.)
python3 -m nuitka --onefile --follow-imports --include-module=readline main.py
./main.bin
```

*(Note: If you want the binary to start up instantly, use `--standalone` instead of `--onefile`. The `--onefile` flag has to extract itself to `/tmp` every time you run it, which kind of defeats the point of optimizing for speed).*

---

### A note on the source code

If you look at the source, it might look a bit weird. I intentionally avoided a lot of the modern Python "niceties" because of the hidden performance costs:

* **No `pathlib`:** I love `Path()`, but creating those objects is surprisingly heavy. I used the older `os.path.join()` everywhere because it's written in C and avoids allocating memory.
* **No `dataclasses`:** Standard classes with `__slots__` are ugly to look at, but they skip dictionary creation and use about 30% less memory per object.
* **No `threading`:** Importing the threading module forces Python to allocate thread-local storage. Since tab completion can load synchronously fast enough, I dropped threads entirely.
* **Lazy Imports:** Modules like `subprocess` and `shlex` aren't imported until the exact millisecond you actually run an external command.

It's a bit pedantic, but it was a fun experiment in seeing how close to "C-speeds" you can get while still writing Python.

**License:** MIT — do whatever you want with it.

*PS: This is just for fun, don't think you'll be able to run this at work.*
