"""Run the existing synthetic Linux rehearsal, retaining logs and an offline review."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def overlaps(left, right):
    return left == right or left in right.parents or right in left.parents


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='New native Linux work directory outside this checkout; retained after the run')
    parser.add_argument('--go', type=Path, help='Existing Go 1.27.2 executable; defaults to go on PATH')
    parser.add_argument('--pg-bin', type=Path,
                        help='Existing PostgreSQL 18.6 bin directory; defaults to pg_config --bindir')
    parser.add_argument('--module-cache', type=Path, help='Optional existing verified Go module cache')
    parser.add_argument('--offline', action='store_true', help='Require cached modules; no dependency download')
    options = parser.parse_args(argv)
    if not sys.platform.startswith('linux') or os.geteuid() == 0:
        parser.error('Run on Linux as a non-root user; PostgreSQL refuses root-owned clusters')
    work = options.output_dir.expanduser().resolve()
    if os.path.lexists(options.output_dir.expanduser()) or overlaps(work, ROOT.resolve()):
        parser.error('--output-dir must be new and must not overlap this checkout')
    go = options.go or shutil.which('go')
    if not go:
        parser.error('Go 1.27.2 is required: add it to PATH or pass --go /path/to/go')
    go = Path(go).expanduser().resolve()
    if not go.is_file() or not os.access(go, os.X_OK):
        parser.error('--go must be an existing executable')
    pgbin = options.pg_bin
    if pgbin is None:
        pgconfig = shutil.which('pg_config')
        if not pgconfig:
            parser.error('PostgreSQL 18.6 is required: add pg_config to PATH or pass --pg-bin')
        try:
            result = subprocess.run([pgconfig, '--bindir'], capture_output=True, text=True,
                                    check=True, timeout=10)
            location = result.stdout.strip()
            if not location or '\n' in location or '\r' in location:
                raise ValueError('pg_config returned an invalid binary directory')
            pgbin = Path(location)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            parser.error('Cannot locate PostgreSQL binaries: ' + str(error))
    pgbin = pgbin.expanduser().resolve()
    for name in ('postgres', 'initdb', 'pg_ctl', 'createdb', 'psql'):
        if not (pgbin / name).is_file() or not os.access(pgbin / name, os.X_OK):
            parser.error('--pg-bin must contain executable ' + name)
    if options.offline and options.module_cache is None:
        parser.error('--offline requires an existing populated --module-cache')
    cache = options.module_cache.expanduser().resolve() if options.module_cache else None
    if cache is not None and (not cache.is_dir() or overlaps(cache, ROOT.resolve()) or overlaps(cache, work)):
        parser.error('--module-cache must exist outside the checkout and the new work directory')
    options.output_dir, options.go, options.pg_bin, options.module_cache = work, go, pgbin, cache
    return options


def run_process(command, work):
    """Interrupt the owned runner gently so its existing finally cleanup can finish."""
    with (work / 'runner.stdout').open('xb') as stdout, (work / 'runner.stderr').open('xb') as stderr:
        child = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            return child.wait()
        except KeyboardInterrupt:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGINT)
            try:
                child.wait(timeout=60)
            except subprocess.TimeoutExpired as error:
                # Do not kill the original cleanup coordinator while it may own a database.
                raise RuntimeError('Runner cleanup is still active; inspect retained logs and PID '
                                   + str(child.pid)) from error
            raise


def interrupt_runner(*_):
    raise KeyboardInterrupt


def main(argv=None):
    options = arguments(argv)
    work = options.output_dir
    # Exclusive creation is also the final race check; never replace an existing output.
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    runs = work / 'runs'
    runs.mkdir(mode=0o700)
    command = [sys.executable, '-B', str(ROOT / 'tools/verify_recovery.py'),
               '--go', str(options.go), '--pg-bin', str(options.pg_bin), '--output-parent', str(runs)]
    if options.module_cache is not None:
        command += ['--module-cache', str(options.module_cache)]
    if options.offline:
        command.append('--offline')
    record = {'status': 'running', 'synthetic_only': True, 'source': str(ROOT),
              'work': str(work), 'original_runner': 'tools/verify_recovery.py',
              'automatic_write_retries_added': False, 'data_retained': True}
    print(json.dumps({'stage': 'running', 'logs': str(work),
                      'scope': 'New synthetic cluster; no existing database connection'}), flush=True)
    code = 1
    try:
        previous = signal.signal(signal.SIGTERM, interrupt_runner)
        try:
            code = run_process(command, work)
        finally:
            signal.signal(signal.SIGTERM, previous)
        record['runner_exit_code'] = code
        receipts = list(runs.glob('*/verification/receipt.json'))
        if len(receipts) != 1:
            raise ValueError('Expected one receipt; inspect preserved runner logs')
        from review_run import write_report
        review = write_report(receipts[0], work / 'review')
        record['review'] = review
        record['receipt'] = str(receipts[0])
        record['report'] = str(work / 'review/report.html')
        record['status'] = 'completed' if code == 0 and review['evidence_passed'] else 'failed'
    except KeyboardInterrupt:
        record['status'], record['error'], code = 'interrupted', 'Interrupted; inspect the retained original receipt for cleanup', 130
    except (OSError, ValueError, RuntimeError) as error:
        record['status'], record['error'], code = 'failed', str(error), 1
    finally:
        (work / 'result.json').write_text(json.dumps(record, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(record, allow_nan=False))
    return 0 if record['status'] == 'completed' else (130 if code == 130 else 1)


if __name__ == '__main__':
    raise SystemExit(main())
