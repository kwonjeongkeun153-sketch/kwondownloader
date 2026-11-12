"""Authenticated, bounded yt-dlp job API for the private POCKET frontend."""
from __future__ import annotations

import hmac
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yt_dlp
from flask import Blueprint, jsonify, request, send_file

api = Blueprint('pocket', __name__, url_prefix='/api/pocket')
ROOT = Path(os.environ.get('POCKET_DOWNLOAD_DIR', '/tmp/pocket-downloads'))
ROOT.mkdir(parents=True, exist_ok=True)
JOBS = {}
LOCK = threading.RLock()
POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pocket')
INFO_GATE = threading.BoundedSemaphore(2)
TTL = 3600
MAX_BYTES = 800 * 1024 * 1024
ACTIVE = {'queued', 'starting', 'downloading', 'processing'}

def clean_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('유튜브 영상 링크를 입력해 주세요.')
    u = urlsplit(value.strip())
    if u.scheme not in ('http', 'https') or u.username or u.password or u.port not in (None, 80, 443):
        raise ValueError('올바른 유튜브 링크가 아닙니다.')
    host = (u.hostname or '').lower()
    if host == 'youtu.be':
        vid = u.path.strip('/').split('/')[0]
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        if u.path == '/watch':
            vid = parse_qs(u.query).get('v', [''])[0]
        elif u.path.startswith(('/shorts/', '/live/', '/embed/')):
            vid = u.path.split('/')[2]
        else:
            vid = ''
    else:
        vid = ''
    if not re.fullmatch(r'[a-zA-Z0-9_-]{11}', vid):
        raise ValueError('단일 유튜브 영상 또는 Shorts 링크를 입력해 주세요.')
    return 'https://www.youtube.com/watch?v=' + vid

def error_message(exc):
    raw = re.sub(r'\x1b\[[0-9;]*m', '', str(exc))
    low = raw.lower()
    if any(x in low for x in ('sign in to confirm', 'not a bot', 'login required')):
        return 'YouTube에서 서버의 접근을 제한했습니다. 이 서버에서는 현재 해당 영상을 받을 수 없습니다.'
    if any(x in low for x in ('private video', 'members-only', 'age-restricted', 'unavailable', 'copyright')):
        return '비공개·접근 제한 또는 사용할 수 없는 영상입니다.'
    if 'failed to extract any player response' in low:
        return '유튜브 영상 정보를 읽지 못했습니다. 다운로드 엔진에서 영상 응답을 처리하지 못했습니다.'
    if 'cancelled' in low:
        return '다운로드를 취소했습니다.'
    if '800' in low or 'two hours' in low:
        return '현재 한도는 영상 2시간, 파일 800 MB입니다.'
    return ('다운로드 서버 오류: ' + raw[-350:])

def options():
    return dict(quiet=True, no_warnings=True, noplaylist=True, socket_timeout=15,
                retries=2, extractor_retries=1, fragment_retries=2,
                js_runtimes={'node': {}}, cachedir=False)

def cleanup():
    now = time.time()
    with LOCK:
        for key, j in list(JOBS.items()):
            if j['status'] not in ACTIVE and now - j['updated'] > TTL:
                shutil.rmtree(ROOT / key, ignore_errors=True)
                del JOBS[key]

@api.before_request
def authorize():
    token = os.environ.get('POCKET_API_TOKEN', '')
    value = request.headers.get('Authorization', '')
    if not token or not hmac.compare_digest(value, 'Bearer ' + token):
        return jsonify(error='인증되지 않은 요청입니다.'), 401
    cleanup()

def public_job(j):
    keys = ('id','status','progress','downloaded','total','speed','eta','title','error','filename','size','created','updated','mode','quality')
    return {key: j.get(key) for key in keys}

@api.get('/health')
def health():
    from yt_dlp.version import __version__
    return jsonify(ok=True, engine=__version__, ffmpeg=bool(shutil.which('ffmpeg')), javascript=bool(shutil.which('node')), retention_seconds=TTL, max_bytes=MAX_BYTES)

@api.post('/info')
def info():
    try:
        url = clean_url((request.get_json(silent=True) or {}).get('url'))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if not INFO_GATE.acquire(blocking=False):
        return jsonify(error='영상 정보를 확인 중입니다. 잠시 후 다시 시도해 주세요.'), 429
    try:
        with yt_dlp.YoutubeDL({**options(), 'skip_download':True}) as ydl:
            data = ydl.extract_info(url, download=False)
        if data.get('is_live'):
            return jsonify(error='진행 중인 라이브는 지원하지 않습니다.'), 400
        if (data.get('duration') or 0) > 7200:
            return jsonify(error='2시간 이하의 영상을 선택해 주세요.'), 400
        heights = sorted({f['height'] for f in data.get('formats', []) if f.get('height') and f.get('vcodec') != 'none'})
        return jsonify(id=data['id'], url=url, title=data.get('title'), channel=data.get('channel') or data.get('uploader'), duration=data.get('duration'), thumbnail='https://i.ytimg.com/vi/' + data['id'] + '/hqdefault.jpg', heights=heights)
    except Exception as exc:
        return jsonify(error=error_message(exc)), 422
    finally:
        INFO_GATE.release()

def run_job(key, url, mode, quality):
    folder = ROOT / key
    folder.mkdir(exist_ok=True)
    with LOCK:
        job = JOBS[key]
        if job['cancel']:
            job.update(status='cancelled', updated=time.time())
            shutil.rmtree(folder, ignore_errors=True)
            return
        job.update(status='starting', updated=time.time())
    def progress(d):
        with LOCK:
            if job['cancel']:
                raise RuntimeError('cancelled')
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            done = d.get('downloaded_bytes') or 0
            if done > MAX_BYTES or total > MAX_BYTES:
                raise RuntimeError('800 MB limit')
            job.update(status='processing' if d['status'] == 'finished' else 'downloading', progress=round(done/total*100,1) if total else None, downloaded=done, total=total, speed=d.get('speed'), eta=d.get('eta'), updated=time.time())
    def post(d):
        with LOCK:
            if job['cancel']:
                raise RuntimeError('cancelled')
            job.update(status='processing', updated=time.time())
    def limit(info, *, incomplete=False):
        if info.get('is_live') or (info.get('duration') or 0) > 7200:
            return 'two hours limit; live streams are unsupported'
    opts = {**options(), 'outtmpl':str(folder / '%(title).100s.%(ext)s'), 'max_filesize':MAX_BYTES, 'progress_hooks':[progress], 'postprocessor_hooks':[post], 'match_filter':limit, 'overwrites':True}
    if mode == 'audio':
        opts.update(format='bestaudio/best', postprocessors=[dict(key='FFmpegExtractAudio', preferredcodec='mp3', preferredquality=quality)])
    else:
        bound = '' if quality == 'best' else '[height<=' + quality + ']'
        opts.update(format=f'bv*[ext=mp4]{bound}+ba[ext=m4a]/b[ext=mp4]{bound}/bv*{bound}+ba/b{bound}', merge_output_format='mp4', postprocessors=[dict(key='FFmpegVideoRemuxer', preferedformat='mp4')])
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info(url, download=True)
        if not result:
            raise RuntimeError('two hours limit or no media found')
        with LOCK:
            if job['cancel']:
                raise RuntimeError('cancelled')
        candidates = [p for p in folder.iterdir() if p.suffix in ('.mp3','.mp4') and p.is_file()]
        if not candidates:
            raise RuntimeError('완성된 미디어 파일이 없습니다. 용량 한도를 초과했을 수 있습니다.')
        target = max(candidates, key=lambda p:p.stat().st_size)
        if target.stat().st_size > MAX_BYTES:
            raise RuntimeError('800 MB limit')
        with LOCK:
            job.update(status='ready', progress=100, title=result.get('title') or target.stem, filename=target.name, size=target.stat().st_size, path=str(target), updated=time.time())
    except Exception as exc:
        with LOCK:
            job.update(status='cancelled' if job['cancel'] else 'error', error=error_message(exc), updated=time.time())
        shutil.rmtree(folder, ignore_errors=True)

@api.post('/jobs')
def create_job():
    data = request.get_json(silent=True) or {}
    try:
        url = clean_url(data.get('url'))
    except ValueError as exc:
        return jsonify(error=str(exc)),400
    mode = data.get('mode','video')
    quality = str(data.get('quality','1080' if mode == 'video' else '192'))
    if mode not in ('video','audio') or quality not in ({'360','480','720','1080','1440','2160','best'} if mode == 'video' else {'128','192','320'}):
        return jsonify(error='지원하지 않는 형식 또는 품질입니다.'),400
    with LOCK:
        if sum(j['status'] in ACTIVE for j in JOBS.values()) >= 3 or len(JOBS) >= 50:
            return jsonify(error='대기열이 가득 찼습니다. 진행 중인 작업이 끝난 뒤 시도해 주세요.'),429
        key = uuid.uuid4().hex
        job = dict(id=key,status='queued',progress=None,title='영상 준비 중',mode=mode,quality=quality,created=time.time(),updated=time.time(),cancel=False)
        JOBS[key]=job
    POOL.submit(run_job,key,url,mode,quality)
    return jsonify(public_job(job)),202

@api.get('/jobs/<key>')
def get_job(key):
    with LOCK:
        job = JOBS.get(key)
        if not job:
            return jsonify(error='작업이 만료되었거나 서버가 재시작되었습니다. 다시 다운로드해 주세요.'),404
        return jsonify(public_job(job))

@api.delete('/jobs/<key>')
def delete_job(key):
    with LOCK:
        job = JOBS.get(key)
        if not job:
            return jsonify(ok=True)
        if job['status'] in ACTIVE:
            job['cancel']=True
            return jsonify(ok=True, cancelling=True)
        shutil.rmtree(ROOT / key, ignore_errors=True)
        del JOBS[key]
    return jsonify(ok=True)

@api.get('/jobs/<key>/file')
def get_file(key):
    with LOCK:
        job = JOBS.get(key)
        if not job or job['status'] != 'ready' or not Path(job.get('path','')).is_file():
            return jsonify(error='파일이 준비되지 않았거나 만료되었습니다.'),404
        target = Path(job['path'])
    response = send_file(target, as_attachment=True, download_name=target.name, conditional=True)
    response.headers['Cache-Control']='private, no-store'
    return response

def init_app(app):
    app.config['MAX_CONTENT_LENGTH']=16 * 1024
    app.register_blueprint(api)
    def sweeper():
        while True:
            time.sleep(60)
            cleanup()
    threading.Thread(target=sweeper,daemon=True,name='pocket-cleanup').start()
