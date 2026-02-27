from __future__ import annotations
import re, struct, sys, os, shutil, traceback
from pathlib import Path
from urllib.parse import urlparse, unquote
from PyQt6 import QtCore, QtGui, QtWidgets
import vlc, requests, whisper

OS_API = "https://api.opensubtitles.com/api/v1"
OS_KEY = os.environ["OPENSUBTITLES_API_KEY"]
OS_USER = os.environ["OPENSUBTITLES_USERNAME"]
OS_PASS = os.environ["OPENSUBTITLES_PASSWORD"]
LANG_MAP = {"eng": "en", "tur": "tr", "fra": "fr", "deu": "de", "spa": "es",
	"ita": "it", "por": "pt", "jpn": "ja", "kor": "ko", "rus": "ru"}

STYLE = ("QWidget{font-family:'Helvetica Neue',Arial,sans-serif;font-size:13px;color:#4a3b4f}"
	"QMainWindow{background:#fff7fb}"
	"QPushButton{background:#f472b6;color:white;border:none;border-radius:8px;padding:8px 14px;font-weight:600}"
	"QPushButton:hover{background:#ec4899}QPushButton:disabled{background:#f1c6df;color:#fff}"
	"QSlider::groove:horizontal{height:8px;background:#ffe4f1;border-radius:4px}"
	"QSlider::handle:horizontal{background:#f472b6;width:16px;height:16px;margin:-4px 0;border-radius:8px}"
	"QSlider::sub-page:horizontal{background:#f472b6;border-radius:4px}"
	"QSlider::add-page:horizontal{background:#ffe4f1;border-radius:4px}"
	"QLabel{font-size:12px;color:#4a3b4f}"
	"QFrame#playlistFrame{background:#fff0f7;border:1px solid #f9a8d4;border-radius:12px}"
	"QListWidget{background:transparent;border:none;outline:none}"
	"QListWidget::item{padding:8px 10px;border-radius:8px}"
	"QListWidget::item:selected{background:#f472b6;color:white}"
	"QListWidget::item:hover{background:#ffe0f0}")
VIDEO_STYLE = "QFrame{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #ffe4f1,stop:1 #fff6fb);border:1px solid #f5b6d6;border-radius:12px}"

def clean_title(stem):
	"""Extract movie/show title from release filename."""
	# Cut at year or common release tags
	name = re.split(r'[\[\(]|\b(19|20)\d{2}\b|\b(720|1080|2160|480)[pPiI]\b|\bWEB|\bBlu[Rr]ay|\bBRRip|\bHDRip|\bWEBRip|\bHDTS|\bx26[45]|\bHEVC|\bAAC|\bH\.?264|\bH\.?265', stem)[0]
	# Replace dots/underscores with spaces, strip
	return re.sub(r'[._]', ' ', name).strip()

def os_hash(path):
	"""OpenSubtitles hash: sum of first+last 64KB as uint64 words + filesize."""
	bs = 64 * 1024; sz = path.stat().st_size
	if sz < bs * 2: return None
	h = sz
	with open(path, "rb") as f:
		for _ in range(bs // 8): h += struct.unpack('<Q', f.read(8))[0]
		f.seek(-bs, 2)
		for _ in range(bs // 8): h += struct.unpack('<Q', f.read(8))[0]
	return f"{h & 0xFFFFFFFFFFFFFFFF:016x}"

def fmt(ms):
	s = max(0, ms // 1000); return f"{s // 60}:{s % 60:02d}"

def srt_ts(sec):
	h, r = divmod(sec, 3600); m, s = divmod(r, 60)
	return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((sec % 1) * 1000):03d}"


class SubtitleWorker(QtCore.QObject):
	finished = QtCore.pyqtSignal(str, object)
	errored = QtCore.pyqtSignal(str)
	progress = QtCore.pyqtSignal(str)

	def __init__(self, path: Path, lang: str = "eng"):
		super().__init__(); self.path, self.lang = path, lang

	def _log(self, msg):
		print(f"[Sub] {msg}", flush=True); self.progress.emit(msg)

	@QtCore.pyqtSlot()
	def run(self):
		try:
			self.progress.emit("Searching OpenSubtitles…")
			result = self._try_opensubtitles()
			if not result:
				self.progress.emit("Providers failed — Whisper fallback…")
				result = self._whisper()
			self.finished.emit(f"Subtitles: {result.name}", result)
		except Exception as e:
			traceback.print_exc(); self.errored.emit(str(e))

	def _try_opensubtitles(self):
		hdr = {"Api-Key": OS_KEY, "User-Agent": "AutoSub v0.1"}
		lang2 = LANG_MAP.get(self.lang, self.lang[:2])
		try:
			# Try hash-based search first (exact match for this file)
			data = []
			fhash = os_hash(self.path)
			if fhash:
				self._log(f"Hash search: {fhash} [{lang2}]")
				r = requests.get(f"{OS_API}/subtitles", headers=hdr,
					params={"moviehash": fhash, "languages": lang2}, timeout=15)
				if r.status_code == 200: data = r.json().get("data", [])
				if data: self._log(f"Hash matched {len(data)} subtitle(s)")
			# Fallback to text search with cleaned title
			if not data:
				title = clean_title(self.path.stem)
				self._log(f"Text search: '{title}' [{lang2}]")
				r = requests.get(f"{OS_API}/subtitles", headers=hdr,
					params={"query": title, "languages": lang2}, timeout=15)
				if r.status_code != 200: self._log(f"Search error: {r.status_code}"); return None
				data = r.json().get("data", [])
			if not data: self._log("No results"); return None
			self._log(f"Found {len(data)} subtitle(s)")
			fid = next((f["file_id"] for e in data for f in e.get("attributes",{}).get("files",[]) if "file_id" in f), None)
			if not fid: return None
			self._log(f"Logging in as {OS_USER}…")
			lr = requests.post(f"{OS_API}/login", headers={**hdr, "Content-Type": "application/json"},
				json={"username": OS_USER, "password": OS_PASS}, timeout=15)
			tok = lr.json().get("token") if lr.status_code == 200 else None
			dl_h = {**hdr, "Content-Type": "application/json"}
			if tok: dl_h["Authorization"] = f"Bearer {tok}"
			dr = requests.post(f"{OS_API}/download", headers=dl_h, json={"file_id": fid}, timeout=15)
			if dr.status_code != 200:
				self._log(f"Download error: {dr.status_code} {dr.text[:200]}")
				if dr.status_code == 406: self.progress.emit(f"Quota exhausted — resets in {dr.json().get('reset_time','?')}")
				return None
			link = dr.json().get("link")
			if not link: return None
			self.progress.emit("Downloading subtitle file…")
			fr = requests.get(link, timeout=30)
			if fr.status_code != 200: return None
			out = self.path.with_suffix(f".{self.lang}.srt")
			out.write_bytes(fr.content); self._log(f"Saved: {out.name}"); return out
		except Exception as e: self._log(f"OpenSubtitles error: {e}"); return None

	def _whisper(self):
		if not shutil.which("ffmpeg"): raise RuntimeError("ffmpeg required for Whisper")
		self._log("Loading Whisper model…"); model = whisper.load_model("large-v3")
		self._log("Transcribing…"); result = model.transcribe(str(self.path), fp16=False)
		lines = [f"{i}\n{srt_ts(s['start'])} --> {srt_ts(s['end'])}\n{s.get('text','').strip()}"
			for i, s in enumerate(result.get("segments", []), 1)]
		out = self.path.with_suffix(".whisper.srt")
		out.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
		self._log(f"Whisper done: {out.name}"); return out


class VideoPlayer(QtWidgets.QMainWindow):
	def __init__(self):
		super().__init__()
		self.setWindowTitle("AutoSub"); self.resize(960, 600)
		self.setAcceptDrops(True); self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
		self.setStyleSheet(STYLE)
		self.instance = vlc.Instance(); self.player = self.instance.media_player_new()
		self.media = None; self.playlist: list[Path] = []; self.current_index = None
		self.is_fullscreen = False; self.saved_geometry = None
		self._threads: dict = {}; self._workers: dict = {}
		self._active: dict = {}; self._q_items: dict = {}
		self._jobs: list = []; self._jid = 0
		self._build_ui()
		self.timer = QtCore.QTimer(self); self.timer.setInterval(200); self.timer.timeout.connect(self._tick)

	def _build_ui(self):
		c = QtWidgets.QWidget(); self._ml = QtWidgets.QHBoxLayout(c)
		self._ml.setContentsMargins(14, 14, 14, 14); self._ml.setSpacing(10)
		# Playlist
		self._pf = QtWidgets.QFrame(); self._pf.setObjectName("playlistFrame")
		self._pf.setFrameStyle(QtWidgets.QFrame.Shape.StyledPanel | QtWidgets.QFrame.Shadow.Raised)
		pl = QtWidgets.QVBoxLayout(self._pf); pl.setContentsMargins(10, 10, 10, 10); pl.setSpacing(8)
		hdr = QtWidgets.QHBoxLayout(); hdr.addWidget(QtWidgets.QLabel("Playlist"))
		self.lang_combo = QtWidgets.QComboBox()
		self.lang_combo.addItem("English", "eng"); self.lang_combo.addItem("Turkish", "tur")
		self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
		hdr.addWidget(self.lang_combo); hdr.addStretch()
		self._activity = QtWidgets.QLabel(""); self._activity.setStyleSheet("color:#d946ef;font-weight:600"); self._activity.hide()
		hdr.addWidget(self._activity)
		self._sel_btn = QtWidgets.QPushButton("Select All"); self._sel_btn.clicked.connect(self._toggle_select); self._sel_btn.hide()
		hdr.addWidget(self._sel_btn)
		for lbl, fn in [("Download Subs", self._download_subs), ("Add Videos", self._add_videos)]:
			b = QtWidgets.QPushButton(lbl); b.clicked.connect(fn); hdr.addWidget(b)
		pl.addLayout(hdr)
		self._plw = QtWidgets.QListWidget(); self._plw.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
		self._plw.itemDoubleClicked.connect(lambda it: self._play_index(self._plw.row(it))); pl.addWidget(self._plw, stretch=1)
		pl.addWidget(QtWidgets.QLabel("Subtitle Queue", styleSheet="font-weight:600"))
		self._qw = QtWidgets.QListWidget(); self._qw.setFixedHeight(100); pl.addWidget(self._qw)
		# Player
		self._rl = QtWidgets.QVBoxLayout()
		self._vf = QtWidgets.QFrame(); self._vf.setObjectName("videoFrame"); self._vf.setStyleSheet(VIDEO_STYLE)
		self._vf.setFrameStyle(QtWidgets.QFrame.Shape.StyledPanel | QtWidgets.QFrame.Shadow.Raised)
		self._vf.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor)); self._vf.installEventFilter(self)
		self._rl.addWidget(self._vf, stretch=1)
		pr = QtWidgets.QHBoxLayout(); self._elapsed = QtWidgets.QLabel("0:00")
		self._slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); self._slider.setRange(0, 1000)
		self._slider.sliderPressed.connect(lambda: self.player.pause() if self.player.is_playing() else None)
		self._slider.sliderReleased.connect(self._seek); self._total = QtWidgets.QLabel("0:00")
		pr.addWidget(self._elapsed); pr.addWidget(self._slider, stretch=1); pr.addWidget(self._total)
		self._prog_w = QtWidgets.QWidget(); self._prog_w.setLayout(pr); self._rl.addWidget(self._prog_w)
		cl = QtWidgets.QHBoxLayout()
		self._play_btn = QtWidgets.QPushButton("Play"); self._play_btn.clicked.connect(self._toggle_play); cl.addWidget(self._play_btn)
		b = QtWidgets.QPushButton("Stop"); b.clicked.connect(self._stop); cl.addWidget(b)
		self._fs_btn = QtWidgets.QPushButton("Fullscreen"); self._fs_btn.clicked.connect(self._toggle_fs); cl.addWidget(self._fs_btn)
		cl.addWidget(QtWidgets.QLabel("Vol"))
		vol = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); vol.setRange(0, 100); vol.setValue(80)
		vol.valueChanged.connect(self.player.audio_set_volume); cl.addWidget(vol); cl.addStretch()
		self._status = QtWidgets.QLabel("Drop a video to start"); cl.addWidget(self._status)
		self._ctrl_w = QtWidgets.QWidget(); self._ctrl_w.setLayout(cl); self._rl.addWidget(self._ctrl_w)
		self._ml.addWidget(self._pf, stretch=0); self._ml.addLayout(self._rl, stretch=1); self.setCentralWidget(c)
		self._ctrl_w.hide(); self._prog_w.hide()

	def _load(self, path):
		self.media = self.instance.media_new(str(path)); self.player.set_media(self.media)
		wid = int(self._vf.winId())
		(self.player.set_nsobject if sys.platform == "darwin" else
		 self.player.set_hwnd if sys.platform.startswith("win") else self.player.set_xwindow)(wid)
		self._status.setText(f"Loaded {path.name}"); self._slider.setValue(0)
		self._elapsed.setText("0:00"); self._total.setText("0:00")
		self.player.play(); self._play_btn.setText("Pause"); self.timer.start()

	def _toggle_play(self):
		if self.player.is_playing(): self.player.pause(); self._play_btn.setText("Play")
		elif self.media: self.player.play(); self._play_btn.setText("Pause"); self.timer.start()
		elif self.playlist: self._play_index(self.current_index or 0)

	def _stop(self):
		self.player.stop(); self._play_btn.setText("Play"); self.timer.stop()
		self._slider.setValue(0); self._elapsed.setText("0:00"); self._total.setText("0:00")
		if self.is_fullscreen: self._toggle_fs()

	def _seek(self):
		if not self.media: return
		self.player.set_position(self._slider.value() / 1000.0)
		if not self.player.is_playing(): self.player.play()
		self._play_btn.setText("Pause")

	def _on_lang_changed(self):
		if self.current_index is None or self.current_index >= len(self.playlist): return
		vid = self.playlist[self.current_index]
		lang = self.lang_combo.currentData() or "eng"
		srt = vid.with_suffix(f".{lang}.srt")
		if srt.exists():
			self.player.video_set_subtitle_file(str(srt))
			self._status.setText(f"Loaded {lang} subtitles")
		else:
			self._status.setText(f"No {lang} subtitle file found")

	def _tick(self):
		if not self.media: return
		ln = self.player.get_length()
		if ln > 0:
			self._slider.blockSignals(True)
			self._slider.setValue(int(self.player.get_time() / ln * 1000))
			self._slider.blockSignals(False)
			self._elapsed.setText(fmt(self.player.get_time())); self._total.setText(fmt(ln))
		if self.player.get_state() in (vlc.State.Ended, vlc.State.Stopped):
			if self.current_index is not None and self.current_index + 1 < len(self.playlist):
				self._play_index(self.current_index + 1)
			else: self._stop()

	def _add_videos(self):
		paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Add Videos", "",
			"Video (*.mp4 *.mkv *.avi *.mov *.wmv *.flv);;All (*)")
		self._enqueue([Path(p) for p in paths])

	def _enqueue(self, paths):
		new = [p for p in paths if p.exists()]
		if not new: return
		auto = self.media is None or self.player.get_state() in (vlc.State.Ended, vlc.State.Stopped)
		for p in new:
			self.playlist.append(p)
			it = QtWidgets.QListWidgetItem(p.name); it.setData(QtCore.Qt.ItemDataRole.UserRole, str(p))
			it.setFlags(it.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
			it.setCheckState(QtCore.Qt.CheckState.Checked); self._plw.addItem(it)
		self._sel_btn.setVisible(self._plw.count() > 0); self._ctrl_w.show(); self._prog_w.show()
		if auto: self._play_index(len(self.playlist) - len(new))
		# Auto-download subtitles for newly added videos
		lang = self.lang_combo.currentData() or "eng"
		existing = {(Path(j["path"]).resolve(), j["lang"]) for j in self._jobs}
		existing |= {(p.resolve(), l) for p, l in self._active.values()}
		for p in new:
			if (p.resolve(), lang) in existing: continue
			self._jid += 1
			self._jobs.append({"id": self._jid, "path": p, "lang": lang})
			it = QtWidgets.QListWidgetItem(f"Queued [{lang}]: {p.name}")
			it.setData(QtCore.Qt.ItemDataRole.UserRole, self._jid)
			it.setData(QtCore.Qt.ItemDataRole.UserRole + 1, p.name)
			self._qw.addItem(it); self._q_items[self._jid] = it
		self._pump()

	def _play_index(self, idx):
		if 0 <= idx < len(self.playlist):
			self.current_index = idx; self._plw.setCurrentRow(idx); self._load(self.playlist[idx])

	def _toggle_select(self):
		n = self._plw.count()
		if not n: return
		on = all(self._plw.item(i).checkState() == QtCore.Qt.CheckState.Checked for i in range(n))
		st = QtCore.Qt.CheckState.Unchecked if on else QtCore.Qt.CheckState.Checked
		for i in range(n): self._plw.item(i).setCheckState(st)

	def _download_subs(self):
		lang = self.lang_combo.currentData() or "eng"
		paths = [Path(self._plw.item(i).data(QtCore.Qt.ItemDataRole.UserRole))
			for i in range(self._plw.count())
			if self._plw.item(i).checkState() == QtCore.Qt.CheckState.Checked
			and self._plw.item(i).data(QtCore.Qt.ItemDataRole.UserRole)]
		if not paths: self._status.setText("Check videos first"); return
		existing = {(Path(j["path"]).resolve(), j["lang"]) for j in self._jobs}
		existing |= {(p.resolve(), l) for p, l in self._active.values()}
		for p in paths:
			if not p.exists() or (p.resolve(), lang) in existing: continue
			self._jid += 1
			self._jobs.append({"id": self._jid, "path": p, "lang": lang})
			it = QtWidgets.QListWidgetItem(f"Queued [{lang}]: {p.name}")
			it.setData(QtCore.Qt.ItemDataRole.UserRole, self._jid)
			it.setData(QtCore.Qt.ItemDataRole.UserRole + 1, p.name)
			self._qw.addItem(it); self._q_items[self._jid] = it
		self._pump()

	def _pump(self):
		while len(self._threads) < 2 and self._jobs:
			job = self._jobs.pop(0); jid, path, lang = job["id"], job["path"], job["lang"]
			w = SubtitleWorker(path, lang); t = QtCore.QThread(self); w.moveToThread(t)
			_j, _p = jid, path
			w.finished.connect(lambda msg, sp, j=_j, vp=_p: self._sub_done(msg, sp, j, vp))
			w.errored.connect(lambda msg, j=_j, vp=_p: self._sub_err(msg, j, vp))
			w.progress.connect(lambda msg, j=_j: self._sub_prog(msg, j))
			w.finished.connect(t.quit); w.errored.connect(t.quit)
			t.finished.connect(t.deleteLater); t.started.connect(w.run)
			self._threads[jid] = t; self._workers[jid] = w; self._active[jid] = (path, lang)
			self._update_q(jid, f"Searching [{lang}]"); t.start()
		n = len(self._jobs) + len(self._threads)
		if n: self._activity.setText(f"Downloading… ({n})"); self._activity.show()
		else: self._activity.hide()

	def _sub_done(self, msg, sub_path, jid, video_path):
		lang = self._active.get(jid, ("", ""))[1]
		self._status.setText(f"{msg} [{lang}]"); self._update_q(jid, f"Done [{lang}]")
		if self.media:
			mrl = self.media.get_mrl()
			if isinstance(mrl, str):
				p = urlparse(mrl)
				cur = Path(unquote(p.path)) if p.scheme == "file" else Path(mrl)
				if cur.resolve() == video_path.resolve() and sub_path:
					self.player.video_set_subtitle_file(str(sub_path))
		self._cleanup(jid)

	def _sub_err(self, msg, jid, _):
		self._status.setText(f"Error: {msg}"); self._update_q(jid, "Failed"); self._cleanup(jid)

	def _sub_prog(self, msg, jid):
		lang = self._active.get(jid, ("", ""))[1]
		self._status.setText(f"{msg} [{lang}]"); self._update_q(jid, f"{msg} [{lang}]")

	def _cleanup(self, jid):
		t = self._threads.pop(jid, None)
		if t and t.isRunning(): t.quit()
		self._workers.pop(jid, None); self._active.pop(jid, None)
		it = self._q_items.pop(jid, None)
		if it: self._qw.takeItem(self._qw.row(it))
		self._pump()

	def _update_q(self, jid, status):
		it = self._q_items.get(jid)
		if it: it.setText(f"{status}: {it.data(QtCore.Qt.ItemDataRole.UserRole + 1) or ''}")

	def dragEnterEvent(self, e):
		e.acceptProposedAction() if e.mimeData().hasUrls() else e.ignore()
	def dropEvent(self, e):
		self._enqueue([Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]); e.acceptProposedAction()
	def eventFilter(self, obj, ev):
		if obj is self._vf and ev.type() == QtCore.QEvent.Type.MouseButtonPress: self._toggle_play(); return True
		return super().eventFilter(obj, ev)

	def keyPressEvent(self, e):
		k = e.key()
		if k == QtCore.Qt.Key.Key_Space: e.accept(); self._toggle_play()
		elif k == QtCore.Qt.Key.Key_Right: e.accept(); self._seek_rel(5000)
		elif k == QtCore.Qt.Key.Key_Left: e.accept(); self._seek_rel(-5000)
		elif k == QtCore.Qt.Key.Key_F: e.accept(); self._toggle_fs()
		elif k == QtCore.Qt.Key.Key_Escape and self.is_fullscreen: e.accept(); self._toggle_fs()
		else: super().keyPressEvent(e)

	def _seek_rel(self, ms):
		if self.media and self.player.get_length() > 0:
			self.player.set_time(max(0, min(self.player.get_length() - 500, self.player.get_time() + ms)))

	def _toggle_fs(self):
		if self.is_fullscreen:
			self.player.set_fullscreen(False); self._ml.setContentsMargins(14,14,14,14); self._ml.setSpacing(10)
			self._vf.setStyleSheet(VIDEO_STYLE)
			self._vf.setFrameStyle(QtWidgets.QFrame.Shape.StyledPanel | QtWidgets.QFrame.Shadow.Raised)
			for w in (self._pf, self._ctrl_w, self._prog_w): w.show()
			if self.saved_geometry: self.setGeometry(self.saved_geometry)
			self.showNormal(); self._fs_btn.setText("Fullscreen")
		else:
			self.saved_geometry = self.geometry(); self._ml.setContentsMargins(0,0,0,0); self._ml.setSpacing(0)
			self._vf.setStyleSheet("QFrame{background:black;border:none}")
			self._vf.setFrameStyle(QtWidgets.QFrame.Shape.NoFrame)
			for w in (self._pf, self._ctrl_w, self._prog_w): w.hide()
			self.showFullScreen(); self.player.set_fullscreen(True); self._fs_btn.setText("Windowed")
		self.is_fullscreen = not self.is_fullscreen

	def closeEvent(self, e):
		for t in list(self._threads.values()):
			if t.isRunning(): t.quit(); t.wait(2000)
		e.accept()

if __name__ == "__main__":
	app = QtWidgets.QApplication(sys.argv); app.setApplicationName("AutoSub")
	w = VideoPlayer(); w.show(); sys.exit(app.exec())
