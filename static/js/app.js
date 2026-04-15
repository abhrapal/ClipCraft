// static/js/app.js
document.addEventListener('DOMContentLoaded', () => {
  const $ = id => document.getElementById(id);

  /* ── Element refs ─────────────────────────────────────────── */
  const uploadForm        = $('uploadForm');
  const videoInput        = $('videoInput');
  const srtInput          = $('srtInput');
  const thumbInput        = $('thumbInput');
  const videoNameDisplay  = $('videoNameDisplay');
  const srtNameDisplay    = $('srtNameDisplay');
  const thumbNameDisplay  = $('thumbNameDisplay');
  const videoNameShort    = $('videoNameShort');
  const uploadStatus      = $('uploadStatus');   // upload-step feedback
  const createStatus      = $('createStatus');   // create-step feedback

  const stepUpload        = $('step-upload');
  const stepCues          = $('step-cues');
  const stepGallery       = $('step-gallery');
  const jobPanel          = $('jobPanel');

  const stepYouTube      = $('step-youtube');

  const navCues           = $('navCues');
  const navGallery        = $('navGallery');
  const navYouTube        = $('navYouTube');
  const navUpload         = $('navUpload');
  const sidebarStatus     = $('sidebarStatus');

  const ytAuthCard       = $('ytAuthCard');
  const ytAuthStatus     = $('ytAuthStatus');
  const ytAuthLabel      = $('ytAuthLabel');
  const ytAuthSpinner    = $('ytAuthSpinner');
  const ytAuthActions    = $('ytAuthActions');
  const ytSetupCard      = $('ytSetupCard');
  const ytUploadForm     = $('ytUploadForm');
  const ytUploadBtn      = $('ytUploadBtn');
  const ytUploadBtnLabel = $('ytUploadBtnLabel');
  const ytUploadStatus   = $('ytUploadStatus');
  const ytUploadQueue    = $('ytUploadQueue');
  const ytClipGrid       = $('ytClipGrid');
  const ytClipGridEmpty  = $('ytClipGridEmpty');
  const ytBulkPanel      = $('ytBulkPanel');
  const ytTitleList      = $('ytTitleList');
  const ytSelectedCount  = $('ytSelectedCount');
  const ytSelNum         = $('ytSelNum');

  const autoNoteToggle    = $('autoNoteToggle');
  const autoWindowInput   = $('autoWindow');
  const autoMinInput      = $('autoMin');
  const maxClipsInput     = $('maxClips');
  const maxDurationInput  = $('maxDuration');

  const selectAllBtn      = $('selectAllBtn');
  const clearAllBtn       = $('clearAllBtn');
  const selectedCountEl   = $('selectedCount');
  const cueList           = $('cueList');
  const createBtn         = $('createBtn');

  const progressFill      = $('progressFill');
  const progressText      = $('progressText');
  const cancelBtn         = $('cancelBtn');
  const clipStatus        = $('clipStatus');

  const clipsGrid         = $('clipsGrid');
  const newJobBtn         = $('newJobBtn');

  const toastContainer    = $('toastContainer');

  /* ── State ────────────────────────────────────────────────── */
  let serverVideoName     = null;
  let serverSrtName       = null;
  let serverThumbnailName = null;
  let cues                = [];
  let selected            = new Set();
  let currentJob          = null;
  let pollTimer           = null;

  /* ── Utils ────────────────────────────────────────────────── */
  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
  }
  function formatTime(s) {
    const sec = Math.floor(s || 0);
    return `${Math.floor(sec / 60).toString().padStart(2,'0')}:${(sec % 60).toString().padStart(2,'0')}`;
  }

  /* ── Toast ────────────────────────────────────────────────── */
  function toast(msg, type = '') {
    if (!toastContainer) return;
    const el = document.createElement('div');
    el.className = 'toast' + (type ? ' ' + type : '');
    el.textContent = msg;
    toastContainer.appendChild(el);
    setTimeout(() => el.remove(), 3800);
  }

  /* ── Nav helpers ──────────────────────────────────────────── */
  function setNavActive(which) {
    // Workflow steps progress linearly: upload → cues → gallery
    // YouTube is a standalone section not part of the linear progression
    const workflowOrder = ['upload', 'cues', 'gallery'];
    const workflowMap   = { upload: navUpload, cues: navCues, gallery: navGallery };
    const wIdx          = workflowOrder.indexOf(which);
    workflowOrder.forEach((step, i) => {
      const el = workflowMap[step];
      if (!el) return;
      el.classList.remove('active', 'done');
      if (wIdx >= 0 && i < wIdx)  el.classList.add('done');
      else if (step === which)    el.classList.add('active');
    });
    // YouTube just toggles active independently
    if (navYouTube) navYouTube.classList.toggle('active', which === 'youtube');
  }

  function showStep(step) {
    [stepCues, stepGallery, jobPanel, stepYouTube].forEach(el => el && el.classList.add('hidden'));
    if (step === 'cues')    { stepCues    && stepCues.classList.remove('hidden');    setNavActive('cues'); }
    if (step === 'gallery') { stepGallery && stepGallery.classList.remove('hidden'); setNavActive('gallery'); }
    if (step === 'youtube') { stepYouTube && stepYouTube.classList.remove('hidden'); setNavActive('youtube'); }
    if (step === 'job')     { jobPanel    && jobPanel.classList.remove('hidden'); }
  }

  // navGallery click — always refresh from server
  if (navGallery) navGallery.addEventListener('click', e => {
    e.preventDefault();
    loadGallery(null, true);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  // navUpload click — scroll back to upload section
  if (navUpload) navUpload.addEventListener('click', e => {
    e.preventDefault();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  /* ── Dropzone visual feedback ─────────────────────────────── */
  function bindDropzone(input, nameEl, dropzoneId) {
    if (!input) return;
    const zone = $(dropzoneId);
    input.addEventListener('change', () => {
      const f = input.files[0];
      if (nameEl) {
        nameEl.textContent = f ? f.name : '';
        nameEl.classList.toggle('hidden', !f);
      }
      if (zone) zone.classList.toggle('filled', !!f);
    });
    if (zone) {
      zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
      zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
      zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('drag-over'); });
    }
  }

  bindDropzone(videoInput, videoNameDisplay, 'dropzoneVideo');
  bindDropzone(srtInput,   srtNameDisplay,   'dropzoneSrt');
  bindDropzone(thumbInput, thumbNameDisplay, 'dropzoneThumb');

  /* ── Upload ───────────────────────────────────────────────── */
  if (uploadForm) uploadForm.addEventListener('submit', async e => {
    e.preventDefault();
    const videoFile = videoInput && videoInput.files[0];
    const srtFile   = srtInput   && srtInput.files[0];
    const thumbFile = thumbInput && thumbInput.files[0];

    if (!videoFile || !srtFile) {
      if (uploadStatus) { uploadStatus.textContent = 'Please select a video and an SRT file.'; uploadStatus.className = 'status-text error'; }
      toast('Select a video and an SRT file.', 'error');
      return;
    }

    const fd = new FormData();
    fd.append('video', videoFile);
    fd.append('srt',   srtFile);
    if (thumbFile) fd.append('thumbnail', thumbFile);

    if (uploadStatus) { uploadStatus.textContent = 'Uploading…'; uploadStatus.className = 'status-text'; }
    if (sidebarStatus) sidebarStatus.textContent = 'Uploading…';

    try {
      const res  = await fetch('/upload', { method: 'POST', body: fd });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Upload failed');
      const data = await res.json();

      serverVideoName     = data.video;
      serverSrtName       = data.srt;
      serverThumbnailName = data.thumbnail || null;

      if (videoNameShort) videoNameShort.textContent = serverVideoName;
      if (uploadStatus)   { uploadStatus.textContent = 'Upload complete ✓'; uploadStatus.className = 'status-text success'; }
      if (sidebarStatus)  sidebarStatus.textContent = serverVideoName;
      toast('Files uploaded successfully.', 'success');

      cues = data.cues || [];
      renderChecklist(cues);
      showStep('cues');
    } catch (err) {
      if (uploadStatus) { uploadStatus.textContent = 'Upload error: ' + err.message; uploadStatus.className = 'status-text error'; }
      toast('Upload error: ' + err.message, 'error');
    }
  });

  /* ── Checklist ────────────────────────────────────────────── */
  function renderChecklist(list) {
    if (!cueList) return;
    cueList.innerHTML = '';
    selected.clear();
    updateSelectionUI();

    const autoEnabled = autoNoteToggle && autoNoteToggle.checked;
    list.forEach(c => {
      const li = document.createElement('li');
      li.className = 'cue-item';

      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.id = `cue_${c.index}`;
      cb.dataset.index = c.index;
      cb.disabled = autoEnabled;

      const lbl = document.createElement('label');
      lbl.htmlFor = cb.id;
      lbl.innerHTML = `<div class="cue-timestamp">${formatTime(c.start)} — ${formatTime(c.end)}</div>
                       <div class="cue-text">${escapeHtml(c.text || '')}</div>`;

      cb.addEventListener('change', ev => {
        const idx = Number(ev.target.dataset.index);
        ev.target.checked ? selected.add(idx) : selected.delete(idx);
        li.classList.toggle('selected', ev.target.checked);
        updateSelectionUI();
      });

      li.appendChild(cb);
      li.appendChild(lbl);
      cueList.appendChild(li);
    });
  }

  function updateSelectionUI() {
    if (!createBtn) return;
    const autoEnabled = autoNoteToggle && autoNoteToggle.checked;
    if (cueList) {
      cueList.querySelectorAll('input[type=checkbox]').forEach(cb => {
        cb.disabled = autoEnabled;
        if (autoEnabled) { cb.checked = false; cb.closest('.cue-item')?.classList.remove('selected'); }
      });
    }
    if (autoEnabled) selected.clear();
    if (selectedCountEl) selectedCountEl.textContent = autoEnabled ? '—' : selected.size;
    createBtn.disabled = !autoEnabled && selected.size === 0;
  }

  if (autoNoteToggle) autoNoteToggle.addEventListener('change', updateSelectionUI);

  if (selectAllBtn) selectAllBtn.addEventListener('click', () => {
    if (!cueList) return;
    cueList.querySelectorAll('input[type=checkbox]').forEach(cb => {
      if (!cb.disabled) { cb.checked = true; cb.closest('.cue-item')?.classList.add('selected'); selected.add(Number(cb.dataset.index)); }
    });
    updateSelectionUI();
  });

  if (clearAllBtn) clearAllBtn.addEventListener('click', () => {
    if (!cueList) return;
    cueList.querySelectorAll('input[type=checkbox]').forEach(cb => { cb.checked = false; cb.closest('.cue-item')?.classList.remove('selected'); });
    selected.clear();
    updateSelectionUI();
  });

  /* ── Create clips ─────────────────────────────────────────── */
  if (createBtn) createBtn.addEventListener('click', async () => {
    if (!serverVideoName || !serverSrtName) {
      toast('Upload a video and SRT first.', 'error');
      return;
    }
    const autoAllowed = autoNoteToggle ? autoNoteToggle.checked : true;
    const sel  = Array.from(selected).map(x => parseInt(x, 10));
    if (sel.length === 0 && !autoAllowed) {
      toast('Select cues or enable Auto-generate.', 'error');
      return;
    }

    const payload = {
      video:              serverVideoName,
      srt:                serverSrtName,
      selected_indices:   sel,
      max_clips:          parseInt(maxClipsInput?.value    || 3,  10),
      auto_window:        parseInt(autoWindowInput?.value  || 45, 10),
      auto_min_duration:  parseInt(autoMinInput?.value     || 30, 10),
      max_duration:       parseInt(maxDurationInput?.value || 60, 10),
      split_x_ratio:      0.5,
      thumbnail:          serverThumbnailName || null,
      embed_thumbnail:    false
    };

    if (createStatus) { createStatus.textContent = sel.length === 0 ? `Auto-generating up to ${payload.max_clips} clips…` : 'Starting…'; createStatus.className = 'status-text'; }
    createBtn.disabled = true;

    try {
      const res  = await fetch('/make_clips', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      if (!res.ok) throw new Error((await res.json().catch(()=>({}))).error || 'Server error');
      const data = await res.json();

      currentJob = data.job_id;
      showStep('job');
      if (clipStatus) clipStatus.innerHTML = '';
      if (progressFill) progressFill.style.width = '0%';
      if (progressText) progressText.textContent = '0%';
      startPolling(currentJob);
    } catch (err) {
      if (createStatus) { createStatus.textContent = 'Error: ' + err.message; createStatus.className = 'status-text error'; }
      toast('Error: ' + err.message, 'error');
      createBtn.disabled = false;
    }
  });

  /* ── Polling ──────────────────────────────────────────────── */
  function startPolling(jobId) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const res = await fetch(`/progress/${jobId}`);
        if (!res.ok) return;
        const p = await res.json();

        if (progressFill) progressFill.style.width = (p.percent || 0) + '%';
        if (progressText) progressText.textContent  = (p.percent || 0) + '%';

        if (clipStatus) {
          clipStatus.innerHTML = '';
          (p.clips || []).forEach(item => {
            const li = document.createElement('li');
            li.textContent = '✓ ' + (typeof item === 'string' ? item : item.clip || '');
            clipStatus.appendChild(li);
          });
          (p.errors || []).forEach(err => {
            const li = document.createElement('li');
            li.className = 'error';
            li.textContent = `✗ cue ${err.cue_index}: ${err.error}`;
            clipStatus.appendChild(li);
          });
        }

        if (p.finished) {
          clearInterval(pollTimer);
          pollTimer = null;
          loadGallery(p.clips || [], true);
          if (createBtn) createBtn.disabled = false;
          toast(`Done — ${(p.clips||[]).length} clip(s) ready.`, 'success');
        }
      } catch (_) {}
    }, 1200);
  }

  if (cancelBtn) cancelBtn.addEventListener('click', async () => {
    if (currentJob) { try { await fetch(`/cancel/${currentJob}`, {method:'POST'}); } catch (_) {} }
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (createBtn) createBtn.disabled = false;
    showStep('cues');
    toast('Job cancelled.');
  });

  /* ── Gallery ──────────────────────────────────────────────── */
  async function loadGallery(files, navigate = true) {
    // If no file list given, fetch all clips from server
    if (!files) {
      try {
        const res  = await fetch('/clips/list');
        const data = await res.json();
        files = (data.clips || []).map(fn => ({ clip: fn, thumbnail: null }));
      } catch (_) { files = []; }
    }

    if (navigate) showStep('gallery');

    const galleryCount = $('galleryCount');
    const galleryEmpty = $('galleryEmpty');
    if (galleryCount) galleryCount.textContent = files.length || '';
    if (galleryEmpty) galleryEmpty.classList.toggle('hidden', files.length > 0);
    if (!clipsGrid) return;
    clipsGrid.innerHTML = '';

    files.forEach(item => {
      const fn    = typeof item === 'string' ? item : item.clip;

      const card = document.createElement('div');
      card.className = 'clip-card';

      const wrap = document.createElement('div');
      wrap.className = 'clip-thumb-wrap';

      const video = document.createElement('video');
      video.className = 'clip-thumb';
      video.src = `/clips/${fn}`;
      video.preload = 'metadata';
      video.setAttribute('playsinline', '');

      const overlay = document.createElement('div');
      overlay.className = 'clip-play-overlay';
      overlay.textContent = '▶';
      overlay.addEventListener('click', () => { video.paused ? video.play() : video.pause(); });

      wrap.appendChild(video);
      wrap.appendChild(overlay);

      const info = document.createElement('div');
      info.className = 'clip-info';
      info.innerHTML = `<div class="clip-name" title="${escapeHtml(fn)}">${escapeHtml(fn)}</div>
                        <a href="/clips/${encodeURIComponent(fn)}" target="_blank" class="btn btn-sm btn-ghost">Open ↗</a>`;

      card.appendChild(wrap);
      card.appendChild(info);
      clipsGrid.appendChild(card);
    });
  }

  const refreshGalleryBtn = $('refreshGalleryBtn');
  if (refreshGalleryBtn) refreshGalleryBtn.addEventListener('click', () => loadGallery(null, true));

  if (newJobBtn) newJobBtn.addEventListener('click', () => {
    // reset state for a new job
    serverVideoName = serverSrtName = serverThumbnailName = null;
    cues = []; selected.clear();
    if (cueList) cueList.innerHTML = '';
    if (clipsGrid) clipsGrid.innerHTML = '';
    if (videoNameDisplay) { videoNameDisplay.textContent = ''; videoNameDisplay.classList.add('hidden'); }
    if (srtNameDisplay)   { srtNameDisplay.textContent   = ''; srtNameDisplay.classList.add('hidden'); }
    if (thumbNameDisplay) { thumbNameDisplay.textContent = ''; thumbNameDisplay.classList.add('hidden'); }
    ['dropzoneVideo','dropzoneSrt','dropzoneThumb'].forEach(id => $(id)?.classList.remove('filled'));
    if (uploadStatus)  { uploadStatus.textContent  = ''; uploadStatus.className  = 'status-text'; }
    if (createStatus)  { createStatus.textContent  = ''; createStatus.className  = 'status-text'; }
    if (sidebarStatus) sidebarStatus.textContent = '';
    if (videoNameShort) videoNameShort.textContent = '';
    if (uploadForm) uploadForm.reset();
    showStep('cues'); // keep cues nav active but section is hidden until next upload
    // actually jump back to upload
    stepCues && stepCues.classList.add('hidden');
    stepGallery && stepGallery.classList.add('hidden');
    jobPanel && jobPanel.classList.add('hidden');
    setNavActive('upload');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  /* ── YouTube ──────────────────────────────────────────────── */
  let ytUploadPollTimers = {};          // uploadId → intervalId
  const ytSelectedClips  = new Set();   // selected clip filenames

  /* ── Render clip selector grid ─────────────────────────── */
  async function loadYtClipGrid() {
    if (!ytClipGrid) return;
    ytClipGrid.innerHTML = '';
    ytSelectedClips.clear();
    updateYtBulkPanel();
    try {
      const res   = await fetch('/clips/list');
      const data  = await res.json();
      const clips = data.clips || [];

      if (clips.length === 0) {
        if (ytClipGridEmpty) ytClipGridEmpty.classList.remove('hidden');
        return;
      }
      if (ytClipGridEmpty) ytClipGridEmpty.classList.add('hidden');

      clips.forEach(fn => {
        const card = document.createElement('div');
        card.className = 'yt-clip-card';
        card.dataset.fn = fn;
        const videoSrc = `/clips/${fn}`;
        card.innerHTML = `
          <div class="yt-clip-thumb-wrap">
            <video class="yt-clip-thumb" src="${videoSrc}" preload="metadata" muted playsinline></video>
            <span class="yt-clip-play">▶</span>
            <span class="yt-select-check">✓</span>
          </div>
          <span class="yt-clip-label">${fn}</span>`;
        card.addEventListener('click', () => toggleYtSelection(fn));
        ytClipGrid.appendChild(card);
      });
    } catch (_) {
      if (ytClipGridEmpty) ytClipGridEmpty.classList.remove('hidden');
    }
  }

  /* ── Toggle selection ──────────────────────────────────── */
  function toggleYtSelection(fn) {
    if (ytSelectedClips.has(fn)) {
      ytSelectedClips.delete(fn);
    } else {
      ytSelectedClips.add(fn);
    }
    // Update card visual
    const card = ytClipGrid?.querySelector(`[data-fn="${CSS.escape(fn)}"]`);
    if (card) card.classList.toggle('selected', ytSelectedClips.has(fn));
    updateYtBulkPanel();
  }

  function updateYtBulkPanel() {
    const count = ytSelectedClips.size;
    // Badge
    if (ytSelectedCount) ytSelectedCount.classList.toggle('hidden', count === 0);
    if (ytSelNum) ytSelNum.textContent = count;
    // Show/hide bulk panel
    if (ytBulkPanel) ytBulkPanel.classList.toggle('hidden', count === 0);
    // Rebuild title list
    if (ytTitleList) {
      const existing = {};
      ytTitleList.querySelectorAll('.yt-title-row').forEach(row => {
        existing[row.dataset.clip] = row.querySelector('.yt-title-input')?.value || '';
      });
      ytTitleList.innerHTML = '';
      ytSelectedClips.forEach(fn => {
        const row = document.createElement('div');
        row.className = 'yt-title-row';
        row.dataset.clip = fn;
        const baseName = fn.replace(/\.[^.]+$/, '').replace(/[-_]/g, ' ');
        const savedVal = existing[fn] || baseName;
        row.innerHTML = `
          <video class="yt-title-thumb" src="/clips/${fn}" preload="metadata" muted playsinline></video>
          <span class="yt-title-filename">${fn}</span>
          <input class="yt-title-input" type="text" placeholder="Video title…" value="${savedVal.replace(/"/g, '&quot;')}" data-clip="${fn}">`;
        ytTitleList.appendChild(row);
      });
    }
    // Upload button label
    if (ytUploadBtnLabel) {
      ytUploadBtnLabel.textContent = count > 0
        ? `Upload ${count} clip${count > 1 ? 's' : ''}`
        : 'Upload';
    }
  }

  /* ── checkYtAuth ───────────────────────────────────────── */
  async function checkYtAuth() {
    try {
      const res  = await fetch('/youtube/status');
      const data = await res.json();
      if (ytAuthSpinner) ytAuthSpinner.style.display = 'none';

      if (!data.configured) {
        if (ytAuthLabel)  { ytAuthLabel.textContent = 'Setup required — no client_secrets.json'; ytAuthStatus.className = 'yt-auth-status disconnected'; }
        if (ytSetupCard)  ytSetupCard.classList.remove('hidden');
        if (ytAuthActions) ytAuthActions.innerHTML = '';
        return;
      }
      if (ytSetupCard) ytSetupCard.classList.add('hidden');

      if (data.authenticated) {
        if (ytAuthLabel)  { ytAuthLabel.textContent = `Connected — ${data.channel || 'YouTube'}`; ytAuthStatus.className = 'yt-auth-status connected'; }
        if (ytAuthActions) ytAuthActions.innerHTML = `<button class="btn btn-ghost btn-sm" id="ytDisconnectBtn">Disconnect</button>`;
        $('ytDisconnectBtn')?.addEventListener('click', async () => {
          await fetch('/youtube/logout', { method: 'POST' });
          ytSelectedClips.clear();
          updateYtBulkPanel();
          if (ytClipGrid) ytClipGrid.innerHTML = '';
          if (ytUploadForm) ytUploadForm.classList.add('hidden');
          checkYtAuth();
        });
        if (ytUploadForm) ytUploadForm.classList.remove('hidden');
        await loadYtClipGrid();
      } else {
        if (ytAuthLabel)  { ytAuthLabel.textContent = 'Not connected'; ytAuthStatus.className = 'yt-auth-status disconnected'; }
        if (ytAuthActions) ytAuthActions.innerHTML = `<a href="/youtube/auth" class="btn btn-primary btn-sm">Connect channel</a>`;
        if (ytUploadForm) ytUploadForm.classList.add('hidden');
      }
    } catch (_) {
      if (ytAuthLabel) ytAuthLabel.textContent = 'Could not reach server';
    }
  }

  if (navYouTube) navYouTube.addEventListener('click', e => {
    e.preventDefault();
    showStep('youtube');
    checkYtAuth();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  /* ── Select All / Clear ────────────────────────────────── */
  $('ytSelectAllBtn')?.addEventListener('click', () => {
    ytClipGrid?.querySelectorAll('.yt-clip-card').forEach(card => {
      const fn = card.dataset.fn;
      if (fn) ytSelectedClips.add(fn);
      card.classList.add('selected');
    });
    updateYtBulkPanel();
  });
  $('ytClearSelBtn')?.addEventListener('click', () => {
    ytSelectedClips.clear();
    ytClipGrid?.querySelectorAll('.yt-clip-card').forEach(c => c.classList.remove('selected'));
    updateYtBulkPanel();
  });

  /* ── Bulk upload button ────────────────────────────────── */
  if (ytUploadBtn) ytUploadBtn.addEventListener('click', async () => {
    const clips = [...ytSelectedClips];
    if (clips.length === 0) { toast('Select at least one clip.', 'error'); return; }

    const desc      = $('ytDescription')?.value?.trim() || '';
    const schedMode = document.querySelector('input[name="schedMode"]:checked')?.value || 'now';

    // Validate titles
    const titles = {};
    let allFilled = true;
    ytTitleList?.querySelectorAll('.yt-title-input').forEach(inp => {
      const v = inp.value.trim();
      if (!v) { inp.classList.add('input-error'); allFilled = false; }
      else    { inp.classList.remove('input-error'); titles[inp.dataset.clip] = v; }
    });
    if (!allFilled) { toast('Fill in all video titles before uploading.', 'error'); return; }

    // Build base scheduled time
    let baseDate = null;
    if (schedMode === 'later') {
      const dateVal = $('ytScheduleDate')?.value;
      const timeVal = $('ytScheduleTime')?.value || '09:00';
      if (!dateVal) { toast('Choose a publish date.', 'error'); return; }
      baseDate = new Date(`${dateVal}T${timeVal}:00`);
      if (isNaN(baseDate.getTime())) { toast('Invalid date/time.', 'error'); return; }
      if (baseDate <= new Date()) { toast('Scheduled time must be in the future.', 'error'); return; }
    }

    ytUploadBtn.disabled = true;
    if (ytUploadStatus) { ytUploadStatus.textContent = `Queuing ${clips.length} clip${clips.length > 1 ? 's' : ''}…`; ytUploadStatus.className = 'status-text'; }
    if (ytUploadQueue) { ytUploadQueue.innerHTML = ''; ytUploadQueue.classList.remove('hidden'); }

    let doneCount = 0;
    let errCount  = 0;

    for (let i = 0; i < clips.length; i++) {
      const fn    = clips[i];
      const title = titles[fn] || fn;

      // Compute staggered scheduled_at (+1 day per clip)
      let scheduled_at = null;
      if (baseDate) {
        const d = new Date(baseDate);
        d.setDate(d.getDate() + i);
        scheduled_at = d.toISOString();
      }

      // Create queue row
      const rowEl = document.createElement('div');
      rowEl.className = 'yt-queue-row';
      rowEl.innerHTML = `
        <div class="yt-queue-row-header">
          <span class="yt-queue-clip-name">${title}</span>
          <span class="yt-queue-state queued">Queued</span>
        </div>
        <div class="yt-queue-bar-wrap"><div class="yt-queue-bar" style="width:0%"></div></div>`;
      ytUploadQueue?.appendChild(rowEl);

      try {
        const res = await fetch('/youtube/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ clip: fn, title, description: desc, scheduled_at }),
        });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Upload failed');
        const data = await res.json();
        pollYtUploadRow(data.upload_id, rowEl, () => {
          doneCount++;
          if (doneCount + errCount === clips.length) finishBulk(doneCount, errCount);
        }, () => {
          errCount++;
          if (doneCount + errCount === clips.length) finishBulk(doneCount, errCount);
        });
      } catch (err) {
        errCount++;
        const stateEl = rowEl.querySelector('.yt-queue-state');
        if (stateEl) { stateEl.textContent = 'Error'; stateEl.className = 'yt-queue-state error'; }
        rowEl.insertAdjacentHTML('beforeend', `<div style="font-size:.75rem;color:var(--danger);margin-top:.25rem">${err.message}</div>`);
        if (doneCount + errCount === clips.length) finishBulk(doneCount, errCount);
      }
    }
  });

  function finishBulk(done, errs) {
    if (ytUploadBtn) ytUploadBtn.disabled = false;
    if (ytUploadStatus) {
      if (errs === 0) {
        ytUploadStatus.textContent = `All ${done} clip${done > 1 ? 's' : ''} uploaded ✓`;
        ytUploadStatus.className   = 'status-text success';
        toast(`${done} clip${done > 1 ? 's' : ''} uploaded to YouTube!`, 'success');
      } else {
        ytUploadStatus.textContent = `${done} uploaded, ${errs} failed`;
        ytUploadStatus.className   = 'status-text error';
        toast(`${done} uploaded, ${errs} failed`, 'error');
      }
    }
  }

  function pollYtUploadRow(uploadId, rowEl, onDone, onError) {
    const barEl   = rowEl.querySelector('.yt-queue-bar');
    const stateEl = rowEl.querySelector('.yt-queue-state');
    if (stateEl) { stateEl.textContent = 'Uploading…'; stateEl.className = 'yt-queue-state uploading'; }

    const timer = setInterval(async () => {
      try {
        const res = await fetch(`/youtube/upload_progress/${uploadId}`);
        if (!res.ok) return;
        const p   = await res.json();
        const pct = p.percent || 0;
        if (barEl) barEl.style.width = pct + '%';
        if (p.finished) {
          clearInterval(timer);
          delete ytUploadPollTimers[uploadId];
          if (p.status === 'done') {
            if (stateEl) { stateEl.textContent = 'Done ✓'; stateEl.className = 'yt-queue-state done'; }
            if (barEl) barEl.style.width = '100%';
            const videoUrl = `https://studio.youtube.com/video/${p.video_id}/edit`;
            rowEl.insertAdjacentHTML('beforeend',
              `<a href="${videoUrl}" target="_blank" class="btn btn-sm btn-ghost" style="margin-top:.35rem;font-size:.75rem">Open in YouTube Studio ↗</a>`);
            if (onDone) onDone();
          } else {
            if (stateEl) { stateEl.textContent = 'Error'; stateEl.className = 'yt-queue-state error'; }
            rowEl.insertAdjacentHTML('beforeend',
              `<div style="font-size:.75rem;color:var(--danger);margin-top:.25rem">${p.error || 'Unknown error'}</div>`);
            if (onError) onError();
          }
        }
      } catch (_) {}
    }, 1500);
    ytUploadPollTimers[uploadId] = timer;
  }

  // Handle redirect back after OAuth
  if (new URLSearchParams(location.search).get('yt_connected') === '1') {
    history.replaceState({}, '', '/');
    showStep('youtube');
    checkYtAuth();
    toast('YouTube channel connected!', 'success');
  }

  /* ── Scheduling UI ──────────────────────────────────────── */
  const schedDateWrap = $('schedDateWrap');
  const ytTimezoneHint = $('ytTimezoneHint');
  // Show local timezone in the hint
  if (ytTimezoneHint) {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    ytTimezoneHint.textContent = `Your local timezone: ${tz}`;
  }
  // Default date/time to tomorrow at 09:00
  const ytScheduleDate = $('ytScheduleDate');
  const ytScheduleTime = $('ytScheduleTime');
  if (ytScheduleDate && ytScheduleTime) {
    const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
    ytScheduleDate.value = tomorrow.toISOString().slice(0, 10);
    ytScheduleTime.value = '09:00';
  }
  document.querySelectorAll('input[name="schedMode"]').forEach(radio => {
    radio.addEventListener('change', () => {
      const later = document.querySelector('input[name="schedMode"]:checked')?.value === 'later';
      if (schedDateWrap) schedDateWrap.classList.toggle('hidden', !later);
    });
  });

  /* ── Initial state ────────────────────────────────────────── */
  stepCues    && stepCues.classList.add('hidden');
  stepGallery && stepGallery.classList.add('hidden');
  stepYouTube && stepYouTube.classList.add('hidden');
  jobPanel    && jobPanel.classList.add('hidden');
  updateSelectionUI();
  // Pre-populate gallery with any clips already on disk (no navigation)
  loadGallery(null, false);
});
