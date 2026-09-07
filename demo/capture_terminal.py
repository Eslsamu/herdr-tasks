#!/usr/bin/env python3
"""Capture real Herdr frames in an isolated PTY, with explicitly scripted chat."""
import fcntl
import html
import json
import os
from pathlib import Path
import pty
import select
import shlex
import struct
import subprocess
import sys
import tempfile
import termios
import time


def shell():
    stage_file = Path(os.environ['DEMO_STAGE'])
    last = None
    while True:
        stage = stage_file.read_text()
        if stage != last:
            last = stage
            lines = [
                '\033[1;36mAgent One\033[0m · example conversation', '',
                '› Draft the release notes for the next version.', '',
                '• I am reviewing the changes and drafting the notes.', '',
            ]
            if int(stage) >= 1:
                lines += ['› Add to the queue: run pre-release regression.',
                          '  Check install, queue claims, and the browser viewer.', '',
                          '• Added task #2. I will finish the release notes first.', '',
                          '  Ran herdr-tasks add "Run pre-release regression"',
                          '  #2 queued', '']
            if int(stage) >= 2:
                lines += ['• Release notes are ready. Task #1 is complete.', '',
                          '  Queue: #2 Run pre-release regression', '',
                          '  Ctrl+B → Ctrl+T opens the space queue.', '']
            if int(stage) >= 3:
                lines += ['• QA picked up task #2 using herdr-tasks next.', '',
                          '  #2 doing · QA', '']
            lines += ['', '› ']
            sys.stdout.write('\033[2J\033[H' + '\r\n'.join(lines))
            sys.stdout.flush()
        time.sleep(.1)


def capture(output, fixture_path):
    import pyte
    fixture = json.loads(Path(fixture_path).read_text())
    with tempfile.TemporaryDirectory(prefix='herdr-terminal-demo-') as tmp:
        root = Path(tmp)
        cwd = root / 'SpaceName'
        cwd.mkdir()
        stage = root / 'stage'
        preview = root / 'preview'
        stage.write_text('0')
        preview.write_text(fixture['working_preview'])
        executable = root / 'demo-shell'
        executable.write_text('#!/bin/sh\nexec ' + shlex.join([sys.executable, str(Path(__file__).resolve()), '--shell']) + '\n')
        executable.chmod(0o700)
        config = root / 'config.toml'
        config.write_text('onboarding = false\n[terminal]\ndefault_shell = ' + json.dumps(str(executable)) + '\nshell_mode = "non_login"\n[update]\nversion_check = false\nmanifest_check = false\n[[ui.tab_bar_right]]\ntype = "command"\ncommand = ' + json.dumps('cat ' + str(preview)) + '\ninterval_seconds = 1\ntimeout_seconds = 1\n')
        env = {k:v for k,v in os.environ.items() if not k.startswith('HERDR_')}
        env.update(HERDR_CONFIG_PATH=str(config), HERDR_SOCKET_PATH=str(root / 'demo.sock'), XDG_CONFIG_HOME=str(root / 'config'), XDG_STATE_HOME=str(root / 'state'), TERM='xterm-256color', DEMO_STAGE=str(stage))
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 44, 104, 0, 0))
        process = subprocess.Popen(['herdr', '--no-session'], stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env, start_new_session=True)
        os.close(slave)
        screen = pyte.Screen(104, 44)
        stream = pyte.ByteStream(screen)
        def drain(seconds):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                if select.select([master], [], [], .05)[0]:
                    stream.feed(os.read(master, 65536))
        def render():
            rows = []
            for y in range(screen.lines):
                row = ''
                for x in range(screen.columns):
                    c = screen.buffer[y][x]
                    fg = '#' + c.fg if len(c.fg) == 6 else {'default':'#cdd6f4','cyan':'#89dceb','green':'#a6e3a1','blue':'#89b4fa','white':'#cdd6f4'}.get(c.fg,c.fg)
                    bg = '#' + c.bg if len(c.bg) == 6 else ('#1e1e2e' if c.bg == 'default' else c.bg)
                    row += '<span style="color:'+fg+';background:'+bg+(' ;font-weight:bold' if c.bold else '')+'">'+html.escape(c.data or ' ')+'</span>'
                rows.append(row)
            return '\n'.join(rows)
        frames = []
        try:
            drain(3)
            os.write(master, b'\x02W')
            drain(.3)
            os.write(master, b'\x15SpaceName\r')
            drain(.5)
            for i in range(4):
                stage.write_text(str(i))
                preview.write_text(fixture['working_preview' if i == 0 else 'pending_preview'] if i < 2 else fixture['queued' if i == 2 else 'doing']['preview'])
                drain(1.5)
                assert process.poll() is None, '\n'.join(screen.display)
                assert 'example conversation' in '\n'.join(screen.display), '\n'.join(screen.display)
                frames.append(render())
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            os.close(master)
        serialized = json.dumps(frames)
        assert '/Users/' not in serialized and 'FindProjectsApp' not in serialized
        Path(output).write_text(serialized)


if __name__ == '__main__':
    if sys.argv[1] == '--shell':
        shell()
    else:
        capture(*sys.argv[1:])
