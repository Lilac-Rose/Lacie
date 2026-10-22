import asyncio
import io
import os
import re
import shutil
import tempfile

import discord
from discord.ext import commands
from discord import app_commands

from utils.logger import get_logger

logger = get_logger(__name__)

MAX_SOURCE_LENGTH = 1500
RENDER_TIMEOUT = 15  # seconds, per subprocess
DPI = 300

# Packages users may pull in with \usepackage{...}; they get hoisted into the preamble.
ALLOWED_PACKAGES = {
    "amsmath", "amssymb", "amsfonts", "amsthm", "mathtools", "bm", "xcolor",
    "tikz", "tikz-cd", "pgfplots", "physics", "siunitx", "mhchem", "chemfig",
    "braket", "cancel", "mathrsfs", "esint", "stmaryrd", "array", "booktabs",
    "multirow", "tabularx", "enumitem", "circuitikz", "forest", "qtree",
}

# Defense in depth on top of openin_any/openout_any=p and -no-shell-escape.
# Anything that reads/writes files, builds control sequence names from strings,
# or re-tokenizes text (which could smuggle the rest past this filter).
BLOCKED_PATTERN = re.compile(
    r"\\(input|include|openin|openout|read|readline|write|immediate|newwrite|newread"
    r"|catcode|csname|scantokens|everyjob|everyeof|special|includegraphics"
    r"|verbatiminput|lstinputlisting|inputminted|pdf\w*|directlua|usetikzlibrary\s*\{\s*external"
    r"|documentclass|begin\s*\{\s*document\s*\}|end\s*\{\s*document\s*\}|endinput|tracing\w*)"
    r"(?![a-zA-Z])"
    r"|\^\^",
    re.IGNORECASE,
)

USEPACKAGE_PATTERN = re.compile(r"\\usepackage\s*(\[[^\]]*\])?\s*\{([^}]*)\}")

# standalone crops the page to the content; the border keeps it readable on dark themes
DOCUMENT_TEMPLATE = r"""\documentclass[12pt,border=10pt,varwidth=6.5in]{{standalone}}
\usepackage[utf8]{{inputenc}}
\usepackage{{amsmath,amssymb,amsfonts}}
{packages}
\begin{{document}}
{body}
\end{{document}}
"""


class LatexError(Exception):
    """Raised when rendering fails, with a user-facing message."""


def build_document(source: str) -> str:
    """Turn user input into a full LaTeX document.

    \\usepackage lines are pulled out and checked against ALLOWED_PACKAGES.
    Input with no math delimiters or environments is treated as a display equation.
    """
    if len(source) > MAX_SOURCE_LENGTH:
        raise LatexError(f"That's too long! Keep it under {MAX_SOURCE_LENGTH} characters.")

    match = BLOCKED_PATTERN.search(source)
    if match:
        raise LatexError(f"`{match.group(0)}` isn't allowed here, sorry!")

    packages = []
    for options, names in USEPACKAGE_PATTERN.findall(source):
        for name in (n.strip() for n in names.split(",")):
            if not name:
                continue
            if name not in ALLOWED_PACKAGES:
                raise LatexError(f"Package `{name}` isn't on the allowed list.")
            packages.append(f"\\usepackage{options}{{{name}}}")
    body = USEPACKAGE_PATTERN.sub("", source).strip()

    if not body:
        raise LatexError("There's nothing to render!")

    if not re.search(r"\$|\\\[|\\\(|\\begin\s*\{", body):
        body = f"\\[\n{body}\n\\]"

    return DOCUMENT_TEMPLATE.format(packages="\n".join(packages), body=body)


def parse_latex_log(log: str) -> str:
    """Pull the first error (line starting with '!') and its context out of a LaTeX log."""
    lines = log.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("!"):
            context = []
            for l in lines[i + 1:i + 4]:
                if not l.strip() or l.startswith("Here is how much"):
                    break
                context.append(l)
            return "\n".join([line] + context)[:900]
    return "LaTeX failed without a readable error."


async def run_process(args: list[str], cwd: str, env: dict) -> tuple[int, str]:
    """Run a subprocess with a timeout, killing it if it runs too long."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=RENDER_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise LatexError("Rendering took too long and was stopped.")
    return proc.returncode, stdout.decode(errors="replace")


async def render_latex(source: str) -> bytes:
    """Render LaTeX source to PNG bytes using pdflatex + Ghostscript in a throwaway directory."""
    if not shutil.which("pdflatex") or not shutil.which("gs"):
        raise LatexError("LaTeX isn't installed on the bot host.")

    document = build_document(source)

    env = os.environ.copy()
    # Restrict TeX file access to the working directory (no absolute paths, no dotfiles, no ..)
    env["openin_any"] = "p"
    env["openout_any"] = "p"
    env["shell_escape"] = "f"

    with tempfile.TemporaryDirectory(prefix="lacie_latex_") as tmp:
        with open(os.path.join(tmp, "render.tex"), "w", encoding="utf-8") as f:
            f.write(document)

        code, _ = await run_process(
            ["pdflatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "render.tex"],
            tmp, env,
        )
        if code != 0:
            log_path = os.path.join(tmp, "render.log")
            log = ""
            if os.path.exists(log_path):
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    log = f.read()
            raise LatexError(f"```\n{parse_latex_log(log)}\n```")

        code, output = await run_process(
            ["gs", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dQUIET", "-sDEVICE=png16m",
             f"-r{DPI}", "-dTextAlphaBits=4", "-dGraphicsAlphaBits=4",
             "-dFirstPage=1", "-dLastPage=1", "-sOutputFile=render.png", "render.pdf"],
            tmp, env,
        )
        png_path = os.path.join(tmp, "render.png")
        if code != 0 or not os.path.exists(png_path):
            logger.error(f"Ghostscript failed: {output}")
            raise LatexError("Couldn't convert the output to an image.")

        with open(png_path, "rb") as f:
            return f.read()


class Latex(commands.Cog):
    """Cog providing the /latex slash command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="latex")
    @app_commands.describe(source="LaTeX to render. Plain input is treated as a display equation.")
    async def latex(self, interaction: discord.Interaction, source: str):
        """Render LaTeX and post it as an image."""
        await interaction.response.defer()
        try:
            png = await render_latex(source)
        except LatexError as e:
            await interaction.followup.send(f"Couldn't render that:\n{e}")
            return
        except Exception as e:
            logger.error(f"LaTeX render crashed: {e}")
            await interaction.followup.send("Something went wrong while rendering.")
            return

        await interaction.followup.send(file=discord.File(io.BytesIO(png), filename="latex.png"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Latex(bot))
