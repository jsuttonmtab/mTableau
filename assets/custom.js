// ─────────────────────────────────────────────
// Tab × button positioning
// ─────────────────────────────────────────────

function positionDeleteBtn() {
    const selectedTab = document.querySelector('.custom-tabs .tab--selected');
    const btn = document.getElementById('delete-worksheet-btn');
    if (!btn || !selectedTab) return;
    const container = selectedTab.closest('[style*="position: relative"]');
    if (!container) return;
    const tabRect       = selectedTab.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    const rightEdge     = tabRect.right - containerRect.left - 18;
    btn.style.left    = rightEdge + 'px';
    btn.style.display = 'block';
}

setTimeout(function() {
    const observer = new MutationObserver(function() { positionDeleteBtn(); });
    observer.observe(document.body, {childList: true, subtree: true});
    positionDeleteBtn();
}, 500);


// ─────────────────────────────────────────────
// Tab right-click context menu
// ─────────────────────────────────────────────

(function() {
    const menu = document.createElement('div');
    menu.id = 'tab-context-menu';
    menu.style.cssText = [
        'position:fixed', 'background:white', 'border:1px solid #dee2e6',
        'border-radius:6px', 'box-shadow:0 4px 12px rgba(0,0,0,0.15)',
        'z-index:9999', 'display:none', 'min-width:160px',
        'padding:4px 0', 'font-size:13px',
    ].join(';');

    menu.innerHTML = '<div id="ctx-rename" style="padding:8px 16px;cursor:pointer;display:flex;align-items:center;gap:8px;">✏️ <span>Rename</span></div>' +
        '<div id="ctx-duplicate" style="padding:8px 16px;cursor:pointer;display:flex;align-items:center;gap:8px;">⧉ <span>Duplicate</span></div>' +
        '<div style="border-top:1px solid #dee2e6;margin:4px 0;"></div>' +
        '<div id="ctx-settings" style="padding:8px 16px;cursor:pointer;display:flex;align-items:center;gap:8px;">⚙️ <span>Worksheet Settings</span></div>';
    document.body.appendChild(menu);

    let targetTab = null;

    ['ctx-rename', 'ctx-duplicate', 'ctx-settings'].forEach(function(id) {
        const el = document.getElementById(id);
        el.addEventListener('mouseenter', function() { el.style.backgroundColor = '#f0f4ff'; });
        el.addEventListener('mouseleave', function() { el.style.backgroundColor = 'white'; });
    });

    function hideTabMenu() { menu.style.display = 'none'; targetTab = null; }

    window._badgeContextHandler = null;

    document.addEventListener('contextmenu', function(e) {
        const tab   = e.target.closest('.custom-tabs .tab');
        const badge = e.target.closest('.draggable-badge');
        if (tab) {
            e.preventDefault(); e.stopPropagation(); hideTabMenu();
            targetTab = tab;
            const x = Math.min(e.clientX, window.innerWidth  - 180);
            const y = Math.min(e.clientY, window.innerHeight - 120);
            menu.style.left = x + 'px'; menu.style.top = y + 'px'; menu.style.display = 'block';
            return;
        }
        if (badge) {
            e.preventDefault(); e.stopPropagation(); hideTabMenu();
            if (window._badgeContextHandler) window._badgeContextHandler(e, badge);
            return;
        }
        hideTabMenu();
        if (window._badgeContextHandler) window._badgeContextHandler(null, null);
    });

    document.addEventListener('click', function(e) { if (!menu.contains(e.target)) hideTabMenu(); });
    document.addEventListener('keydown', function(e) { if (e.key === 'Escape') hideTabMenu(); });

    document.getElementById('ctx-rename').addEventListener('click', function() {
        if (!targetTab) return;
        const currentName = targetTab.textContent.trim();
        hideTabMenu();
        
        // Create overlay dialog
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center;';
        
        const dialog = document.createElement('div');
        dialog.style.cssText = 'background:white;border-radius:8px;padding:20px;min-width:300px;box-shadow:0 4px 20px rgba(0,0,0,0.3);';
        dialog.innerHTML = `
            <div style="font-weight:bold;margin-bottom:12px;font-size:14px;">Rename Worksheet</div>
            <input type="text" id="rename-input" value="${currentName}" 
                   style="width:100%;padding:6px 10px;border:1px solid #ccc;border-radius:4px;font-size:13px;box-sizing:border-box;" />
            <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px;">
                <button id="rename-cancel" style="padding:4px 16px;border:1px solid #ccc;border-radius:4px;background:white;cursor:pointer;font-size:12px;">Cancel</button>
                <button id="rename-ok" style="padding:4px 16px;border:none;border-radius:4px;background:#0d6efd;color:white;cursor:pointer;font-size:12px;">Rename</button>
            </div>
        `;
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);
        
        const input = document.getElementById('rename-input');
        input.select();
        input.focus();
        
        function doRename() {
            const newName = input.value.trim();
            document.body.removeChild(overlay);
            if (!newName || newName === currentName) return;
            window._dashRenamePayload = JSON.stringify({from: currentName, to: newName});
            const btn = document.getElementById('rename-trigger-btn');
            if (btn) btn.click();
        }
        
        function doCancel() {
            document.body.removeChild(overlay);
        }
        
        document.getElementById('rename-ok').addEventListener('click', doRename);
        document.getElementById('rename-cancel').addEventListener('click', doCancel);
        overlay.addEventListener('click', function(e) { if (e.target === overlay) doCancel(); });
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') doRename();
            if (e.key === 'Escape') doCancel();
        });
    });

    document.getElementById('ctx-duplicate').addEventListener('click', function() {
        if (!targetTab) return;
        const tabName = targetTab.textContent.trim(); hideTabMenu();
        window._dashDupePayload = tabName;
        const btn = document.getElementById('dupe-trigger-btn');
        if (btn) btn.click();
    });

    document.getElementById('ctx-settings').addEventListener('click', function() {
        if (!targetTab) return;
        const tabName = targetTab.textContent.trim(); hideTabMenu();
        window._dashWsSettingsPayload = tabName;
        const btn = document.getElementById('ws-settings-trigger-btn');
        if (btn) btn.click();
    });
})();


// ─────────────────────────────────────────────
// Badge right-click menu + Mouse-based Drag and Drop
//
// pywebview blocks HTML5 drag events at the OS level.
// We simulate drag with mousedown + mousemove + mouseup.
// ─────────────────────────────────────────────

(function() {

// ── Date format options ───────────────────
    const DATE_FORMAT_OPTIONS = [
        {value: 'none',              label: 'Default (Mon/Yr)'},
        {value: 'quarter',           label: 'Quarter (Q1 2025)'},
        {value: 'year',              label: 'Year (2025)'},
    ];
    
    const DATE_FIELDS = new Set(['TABRUN_MY', 'ACTION_DATE', 'TABRUN_TS']);

    // ── Badge context menu ────────────────────
    const badgeMenu = document.createElement('div');
    badgeMenu.id = 'badge-context-menu';
    badgeMenu.style.cssText = 'position:fixed;background:white;border:1px solid #dee2e6;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,0.15);z-index:9999;display:none;min-width:160px;padding:4px 0;font-size:13px;';
    document.body.appendChild(badgeMenu);

    const fmtMenu = document.createElement('div');
    fmtMenu.id = 'badge-format-submenu';
    fmtMenu.style.cssText = 'position:fixed;background:white;border:1px solid #dee2e6;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,0.15);z-index:10000;display:none;min-width:200px;padding:4px 0;font-size:13px;';
    document.body.appendChild(fmtMenu);

    let _badgeTarget  = null;
    let _currentFmt   = 'none';
    let _fmtMenuTimer = null;

    function hideBadgeMenu() {
        badgeMenu.style.display = 'none';
        fmtMenu.style.display   = 'none';
        _badgeTarget = null;
    }

    window._badgeContextHandler = function(e, badge) {
        if (!badge) { hideBadgeMenu(); return; }
        _badgeTarget = badge;
        _currentFmt  = badge.getAttribute('data-fmt') || 'none';
        const field  = badge.getAttribute('data-field') || '';
        buildBadgeMenu(DATE_FIELDS.has(field));
        const x = Math.min(e.clientX, window.innerWidth  - 180);
        const y = Math.min(e.clientY, window.innerHeight - 220);
        badgeMenu.style.left = x + 'px'; badgeMenu.style.top = y + 'px'; badgeMenu.style.display = 'block';
    };

    function makeBadgeItem(html, hoverColor, onClick) {
        const item = document.createElement('div');
        item.style.cssText = 'padding:8px 16px;cursor:pointer;display:flex;align-items:center;gap:8px;';
        item.innerHTML = html;
        item.addEventListener('mouseenter', function() { item.style.backgroundColor = hoverColor; });
        item.addEventListener('mouseleave', function() { item.style.backgroundColor = 'white'; });
        item.addEventListener('click', onClick);
        return item;
    }

    function fireBadgePayload(payload) {
        hideBadgeMenu();
        window._dashBadgeContextPayload = JSON.stringify(payload);
        setTimeout(function() {
            const btn = document.getElementById('badge-context-trigger-btn');
            if (btn) btn.click();
        }, 50);
    }

    function buildBadgeMenu(isDateField) {
        badgeMenu.innerHTML = '';
        badgeMenu.appendChild(makeBadgeItem('🔽 <span>Filter</span>', '#f0f4ff', function() {
            if (!_badgeTarget) return;
            fireBadgePayload({ field: _badgeTarget.getAttribute('data-field'), worksheet: _badgeTarget.getAttribute('data-worksheet'), shelf: _badgeTarget.getAttribute('data-source-shelf'), tab: 'filter' });
        }));
        if (isDateField) {
            const sep = document.createElement('div');
            sep.style.cssText = 'border-top:1px solid #dee2e6;margin:4px 0;';
            badgeMenu.appendChild(sep);
            const fmtItem = makeBadgeItem('<span style="display:flex;align-items:center;gap:8px;">📅 <span>Format</span></span><span style="color:#999;font-size:11px;margin-left:auto;">▶</span>', '#f0f4ff', function() {});
            fmtItem.style.justifyContent = 'space-between';
            fmtItem.addEventListener('mouseenter', function() { clearTimeout(_fmtMenuTimer); showFormatSubmenu(fmtItem); });
            fmtItem.addEventListener('mouseleave', function() {
                _fmtMenuTimer = setTimeout(function() { if (!fmtMenu.matches(':hover')) fmtMenu.style.display = 'none'; }, 200);
            });
            badgeMenu.appendChild(fmtItem);
        }
    }

    function showFormatSubmenu(fmtItem) {
        const field     = _badgeTarget ? _badgeTarget.getAttribute('data-field') : '';
        const worksheet = _badgeTarget ? _badgeTarget.getAttribute('data-worksheet') : '';
        const shelf     = _badgeTarget ? _badgeTarget.getAttribute('data-source-shelf') : '';
        fmtMenu.innerHTML = '';
        DATE_FORMAT_OPTIONS.forEach(function(opt) {
            const item = document.createElement('div');
            item.style.cssText = 'padding:7px 16px;cursor:pointer;display:flex;align-items:center;gap:8px;';
            item.innerHTML = '<span style="font-family:monospace;color:#0f1f3d;">' + (_currentFmt === opt.value ? '●' : ' ') + '</span><span>' + opt.label + '</span>';
            item.addEventListener('mouseenter', function() { item.style.backgroundColor = '#f0f4ff'; });
            item.addEventListener('mouseleave', function() { item.style.backgroundColor = 'white'; });
            item.addEventListener('click', function() {
                fireBadgePayload({ field: field, worksheet: worksheet, shelf: shelf, tab: 'format', fmt: opt.value });
            });
            fmtMenu.appendChild(item);
        });
        const r = badgeMenu.getBoundingClientRect();
        let x = r.right + 2, y = r.top + fmtItem.offsetTop;
        if (x + 210 > window.innerWidth)  x = r.left - 210;
        if (y + 220 > window.innerHeight) y = window.innerHeight - 230;
        fmtMenu.style.left = x + 'px'; fmtMenu.style.top = y + 'px'; fmtMenu.style.display = 'block';
    }

    fmtMenu.addEventListener('mouseenter', function() { clearTimeout(_fmtMenuTimer); });
    fmtMenu.addEventListener('mouseleave', function() { fmtMenu.style.display = 'none'; });
    document.addEventListener('click', function(e) { if (!badgeMenu.contains(e.target) && !fmtMenu.contains(e.target)) hideBadgeMenu(); });
    document.addEventListener('keydown', function(e) { if (e.key === 'Escape') hideBadgeMenu(); });


    // ── Mouse-based drag and drop ─────────────
    // HTML5 drag events are blocked by pywebview at the OS level.
    // We use mousedown + mousemove + mouseup to simulate drag and drop.

    let dragData        = null;
    let insertBefore    = null;
    let insertAfter     = null;
    let isDragging      = false;
    let dragSource      = null;
    let ghost           = null;
    let activeZone      = null;
    let mouseDownPos    = null;
    let pendingDragData = null;
    const DRAG_THRESHOLD = 5;

    function clearInsertIndicators() {
        document.querySelectorAll('.draggable-badge').forEach(function(b) {
            b.style.borderLeft = ''; b.style.borderRight = '';
        });
        insertBefore = null; insertAfter = null;
    }

    function createGhost(label) {
        ghost = document.createElement('div');
        ghost.style.cssText = 'position:fixed;background:#0f1f3d;color:white;padding:4px 10px;border-radius:4px;font-size:12px;pointer-events:none;z-index:99999;opacity:0.85;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,0.3);';
        ghost.textContent = label;
        document.body.appendChild(ghost);
    }

    function removeGhost() { if (ghost) { ghost.remove(); ghost = null; } }

    function moveGhost(x, y) { if (ghost) { ghost.style.left = (x + 12) + 'px'; ghost.style.top = (y + 12) + 'px'; } }

    function getDropZoneAt(x, y) {
        // Use bounding rect geometry instead of elementFromPoint —
        // elementFromPoint is unreliable in pywebview because the ghost
        // element intercepts the hit test even when hidden asynchronously.
        const zones = document.querySelectorAll('.drop-zone');
        for (let i = 0; i < zones.length; i++) {
            const rect = zones[i].getBoundingClientRect();
            if (x >= rect.left && x <= rect.right &&
                y >= rect.top  && y <= rect.bottom) {
                return zones[i];
            }
        }
        return null;
    }

    function highlightZone(zone) {
        if (activeZone === zone) return;
        if (activeZone) activeZone.classList.remove('drop-zone-hover');
        activeZone = zone;
        if (activeZone) activeZone.classList.add('drop-zone-hover');
    }

    function getDragDataFromElement(el) {
        const badge = el.closest('.draggable-badge');
        const field = el.closest('.draggable-field');
        if (badge) {
            return { field: badge.getAttribute('data-field'), source: badge.getAttribute('data-source-shelf'), worksheet: badge.getAttribute('data-worksheet'), label: badge.getAttribute('data-field') };
        }
        if (field) {
            const idx = field.getAttribute('data-field-index') || '';
            const parts = idx.split('|');
            let fieldName = (parts.length === 3 && parts[1] === 'calc') ? ('calc_' + parts[2]) : (parts[1] || idx);
            return { field: fieldName, source: 'panel', worksheet: parts[0] || '', label: fieldName };
        }
        return null;
    }

    function cancelDrag() {
        isDragging = false; removeGhost();
        document.body.style.userSelect = '';
        if (dragSource) { dragSource.style.opacity = '1'; dragSource = null; }
        if (activeZone) { activeZone.classList.remove('drop-zone-hover'); activeZone = null; }
        clearInsertIndicators();
        dragData = null; pendingDragData = null; mouseDownPos = null;
    }

    // Block native HTML5 drag so our mouse-based drag gets mousemove events
    document.addEventListener('dragstart', function(e) {
        const badge = e.target.closest('.draggable-badge');
        const field = e.target.closest('.draggable-field');
        if (badge || field) e.preventDefault();
    });

    document.addEventListener('mousedown', function(e) {
        if (e.button !== 0) return;
        if (e.target.closest('button, input, select, textarea, a')) return;
        if (e.target.closest('#badge-context-menu, #badge-format-submenu, #tab-context-menu')) return;
        if (e.target.closest('td, th')) return; // allow text selection in table cells
        const data = getDragDataFromElement(e.target);
        if (!data) return;
        e.preventDefault(); // prevent text selection interfering with drag
        pendingDragData = data;
        mouseDownPos    = { x: e.clientX, y: e.clientY };
        dragSource      = e.target.closest('.draggable-badge') || e.target.closest('.draggable-field');
    });

    window.addEventListener('mousemove', function(e) {
        if (!pendingDragData) return;
        if (!isDragging) {
            const dx = e.clientX - mouseDownPos.x;
            const dy = e.clientY - mouseDownPos.y;
            if (Math.sqrt(dx*dx + dy*dy) < DRAG_THRESHOLD) return;
            isDragging = true;
            dragData   = pendingDragData;
            createGhost(dragData.label);
            if (dragSource) dragSource.style.opacity = '0.4';
            document.body.style.userSelect = 'none';
        }
        moveGhost(e.clientX, e.clientY);
        highlightZone(getDropZoneAt(e.clientX, e.clientY));
        clearInsertIndicators();
        if (activeZone) {
            // Use geometry check to find badge under cursor
            let badgeEl = null;
            activeZone.querySelectorAll('.draggable-badge').forEach(function(b) {
                const r = b.getBoundingClientRect();
                if (e.clientX >= r.left && e.clientX <= r.right &&
                    e.clientY >= r.top  && e.clientY <= r.bottom) {
                    badgeEl = b;
                }
            });
            if (badgeEl && activeZone.contains(badgeEl)) {
                const rect = badgeEl.getBoundingClientRect();
                if (e.clientX < rect.left + rect.width / 2) {
                    badgeEl.style.borderLeft = '3px solid #0f1f3d';
                    insertBefore = badgeEl.getAttribute('data-field');
                } else {
                    badgeEl.style.borderRight = '3px solid #0f1f3d';
                    insertAfter = badgeEl.getAttribute('data-field');
                }
            }
        }
    });

    // Listen on window to catch mouseup even when pywebview intercepts on child elements
    window.addEventListener('mouseup', function(e) {
        if (!isDragging) {
            pendingDragData = null; mouseDownPos = null; dragSource = null;
            return;
        }
        // Remove ghost immediately so user sees feedback right away
        removeGhost();
        // Use activeZone tracked during mousemove — getDropZoneAt fails in pywebview
        // because the ghost element blocks elementFromPoint synchronously.
        const zone = activeZone;
        const data = dragData;
        const ib   = insertBefore;
        const ia   = insertAfter;
        cancelDrag();

        if (zone && data && data.field) {
            window._dashDropPayload = JSON.stringify({
                field:         data.field,
                shelf:         zone.getAttribute('data-shelf'),
                worksheet:     zone.getAttribute('data-worksheet'),
                source:        data.source || 'panel',
                insert_before: ib || null,
                insert_after:  ia || null,
            });
            console.log('[mTab] drop payload:', window._dashDropPayload);
            const btn = document.getElementById('drop-trigger-btn');
            if (btn) btn.click();
        }
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && isDragging) cancelDrag();
    });

    // ── Tab delete × click ────────────────────
    document.addEventListener('click', function(e) {
        const tab = e.target.closest('.custom-tabs .tab');
        if (!tab) return;
        const rect   = tab.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        if (clickX > rect.width - 24) {
            e.stopPropagation(); e.preventDefault();
            window._dashDeletePayload = tab.textContent.trim();
            const btn = document.getElementById('delete-ws-trigger-btn');
            if (btn) btn.click();
        }
    });

})();


// ─────────────────────────────────────────────
// Resizable HTML table columns
// ─────────────────────────────────────────────

function setColWidth(tbl, idx, w) {
    tbl.querySelectorAll('tr').forEach(function(row) {
        const cell = row.children[idx];
        if (!cell) return;
        cell.style.width = w + 'px'; cell.style.minWidth = w + 'px'; cell.style.maxWidth = w + 'px';
    });
}

function lockAllColumns(tbl) {
    tbl.querySelectorAll('th').forEach(function(th, idx) {
        setColWidth(tbl, idx, th.getBoundingClientRect().width);
    });
    tbl.style.tableLayout = 'fixed'; tbl.style.width = 'max-content';
}

function autoSizeCol(tbl, idx) {
    let maxW = 0;
    tbl.querySelectorAll('tr').forEach(function(row) {
        const cell = row.children[idx];
        if (!cell) return;
        const span = document.createElement('span');
        span.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;font-size:' + getComputedStyle(cell).fontSize + ';font-family:' + getComputedStyle(cell).fontFamily + ';padding:' + getComputedStyle(cell).padding + ';';
        span.textContent = cell.textContent || '';
        document.body.appendChild(span);
        maxW = Math.max(maxW, span.offsetWidth);
        document.body.removeChild(span);
    });
    setColWidth(tbl, idx, maxW + 8);
}

function initResizable() {
    document.querySelectorAll('.col-resizer').forEach(function(resizer) {
        if (resizer._init) return;
        resizer._init = true;
        const th = resizer.parentElement;
        resizer.addEventListener('dblclick', function(e) {
            e.preventDefault(); e.stopPropagation();
            const tbl = th.closest('table');
            autoSizeCol(tbl, Array.from(th.parentNode.children).indexOf(th));
            tbl.style.tableLayout = 'fixed'; tbl.style.width = 'max-content';
        });
        resizer.addEventListener('mousedown', function(e) {
            e.preventDefault(); e.stopPropagation();
            const tbl = th.closest('table');
            const idx = Array.from(th.parentNode.children).indexOf(th);
            const startX = e.pageX;
            lockAllColumns(tbl);
            const startW = th.getBoundingClientRect().width;
            function onMove(e) { setColWidth(tbl, idx, Math.max(40, startW + (e.pageX - startX))); }
            function onUp()   { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); }
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    });
}

let _resizeObserverActive = false;
setTimeout(function() {
    if (_resizeObserverActive) return;
    _resizeObserverActive = true;
    new MutationObserver(function(mutations) {
        let hasNew = false;
        mutations.forEach(function(m) {
            m.addedNodes.forEach(function(n) {
                if (n.nodeType === 1) {
                    if (n.classList && n.classList.contains('col-resizer')) hasNew = true;
                    if (n.querySelector && n.querySelector('.col-resizer:not([data-init])')) hasNew = true;
                }
            });
        });
        if (hasNew) initResizable();
    }).observe(document.body, {childList: true, subtree: true});
    initResizable();
}, 500);


// ─────────────────────────────────────────────
// Extract running clock (pure JS)
// ─────────────────────────────────────────────

(function() {
    let _extractStart  = null;
    let _clockInterval = null;

    function formatTime(s) { var m = Math.floor(s/60); return m + 'm ' + String(s%60).padStart(2,'0') + 's'; }

    function startClock() {
        if (_clockInterval) return;
        _extractStart = Date.now();
        _clockInterval = setInterval(function() {
            var t = formatTime(Math.floor((Date.now() - _extractStart) / 1000));
            var d = document.getElementById('extract-clock-display');
            var c = document.getElementById('extract-clock');
            if (d) d.textContent = '⏱ Extract running — ' + t;
            if (c) c.style.display = 'block';
            var sc = document.getElementById('settings-extract-clock');
            if (sc) { sc.textContent = '⏱ Extract running — ' + t; sc.style.display = 'block'; }
        }, 1000);
    }

    function stopClock() {
        if (_clockInterval) { clearInterval(_clockInterval); _clockInterval = null; }
        _extractStart = null;
        var c = document.getElementById('extract-clock');
        if (c) c.style.display = 'none';
        var sc = document.getElementById('settings-extract-clock');
        if (sc) sc.style.display = 'none';
    }

    document.addEventListener('click', function(e) {
        if (e.target.closest('#settings-refresh-btn, #refresh-extract-btn')) startClock();
    });

    new MutationObserver(function() {
        var msg = document.getElementById('extract-progress-display');
        if (!msg || !_clockInterval) return;
        var t = msg.textContent || '';
        if (t.startsWith('✅') || t.startsWith('❌') || t.startsWith('⚠️')) stopClock();
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
})();

document.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
        const searchBox = document.getElementById('perm-filter-search');
        if (document.activeElement === searchBox) {
            const btn = document.getElementById('perm-filter-search-btn');
            if (btn) btn.click();
        }
    }
});

// ─────────────────────────────────────────────
// Column sort by clicking headers
// ─────────────────────────────────────────────

(function() {
    let sortState = {}; // { colIndex: 'asc' | 'desc' | 'original' }
    let originalRows = null;
    let currentTable = null;

    function resetSortState(tbl) {
        sortState = {};
        originalRows = null;
        currentTable = null;
        // Remove sort indicators
        tbl.querySelectorAll('th .sort-indicator').forEach(function(el) { el.remove(); });
    }

    function saveOriginalOrder(tbl) {
        const tbody = tbl.querySelector('tbody');
        if (!tbody) return;
        originalRows = Array.from(tbody.querySelectorAll('tr')).map(function(tr) {
            return tr.cloneNode(true);
        });
        currentTable = tbl;
    }

    function updateSortIndicators(tbl, sortedCol, direction) {
        tbl.querySelectorAll('th .sort-indicator').forEach(function(el) { el.remove(); });
        if (direction === 'original') return;
        const ths = tbl.querySelectorAll('thead th');
        if (sortedCol < ths.length) {
            const indicator = document.createElement('span');
            indicator.className = 'sort-indicator';
            indicator.style.cssText = 'margin-left:4px;font-size:10px;opacity:0.8;';
            indicator.textContent = direction === 'asc' ? '▲' : '▼';
            ths[sortedCol].appendChild(indicator);
        }
    }

    function sortTable(tbl, colIndex, direction) {
        const tbody = tbl.querySelector('tbody');
        if (!tbody) return;

        if (direction === 'original') {
            if (originalRows) {
                tbody.innerHTML = '';
                originalRows.forEach(function(tr) { tbody.appendChild(tr.cloneNode(true)); });
            }
            updateSortIndicators(tbl, colIndex, 'original');
            return;
        }

        const rows = Array.from(tbody.querySelectorAll('tr'));
        
        // Separate Grand Total row(s) — keep them in place
        const grandTotalRows = [];
        const dataRows = [];
        rows.forEach(function(row) {
            const firstCell = row.querySelector('td');
            if (firstCell && firstCell.textContent.trim() === 'Grand Total') {
                grandTotalRows.push({ row: row, index: rows.indexOf(row) });
            } else {
                dataRows.push(row);
            }
        });

        dataRows.sort(function(a, b) {
            const cellA = a.children[colIndex];
            const cellB = b.children[colIndex];
            if (!cellA || !cellB) return 0;
            let valA = cellA.textContent.trim();
            let valB = cellB.textContent.trim();

            // Handle blank cells (row blanking) — treat as same as previous
            if (valA === '') valA = '\x00';
            if (valB === '') valB = '\x00';

            // Try numeric comparison
            const numA = parseFloat(valA.replace(/,/g, ''));
            const numB = parseFloat(valB.replace(/,/g, ''));
            if (!isNaN(numA) && !isNaN(numB)) {
                return direction === 'asc' ? numA - numB : numB - numA;
            }

            // String comparison
            const cmp = valA.localeCompare(valB, undefined, { numeric: true, sensitivity: 'base' });
            return direction === 'asc' ? cmp : -cmp;
        });

        tbody.innerHTML = '';
        // Rebuild: if Grand Total was first, keep it first
        if (grandTotalRows.length > 0 && grandTotalRows[0].index === 0) {
            grandTotalRows.forEach(function(gt) { tbody.appendChild(gt.row); });
            dataRows.forEach(function(row) { tbody.appendChild(row); });
        } else {
            dataRows.forEach(function(row) { tbody.appendChild(row); });
            grandTotalRows.forEach(function(gt) { tbody.appendChild(gt.row); });
        }

        updateSortIndicators(tbl, colIndex, direction);
    }

    document.addEventListener('click', function(e) {
        const th = e.target.closest('.mtab-table th');
        if (!th) return;
        // Don't sort if clicking the resizer
        if (e.target.closest('.col-resizer')) return;

        const tbl = th.closest('table');
        if (!tbl || !tbl.classList.contains('mtab-table')) return;

        const colIndex = Array.from(th.parentNode.children).indexOf(th);

        // Save original order on first sort
        if (currentTable !== tbl || !originalRows) {
            saveOriginalOrder(tbl);
            sortState = {};
        }

        // Cycle: none → asc → desc → original
        const current = sortState[colIndex] || 'none';
        let next;
        if (current === 'none') next = 'asc';
        else if (current === 'asc') next = 'desc';
        else next = 'original';

        // Reset other columns
        Object.keys(sortState).forEach(function(k) {
            if (parseInt(k) !== colIndex) sortState[k] = 'none';
        });

        sortState[colIndex] = next === 'original' ? 'none' : next;
        sortTable(tbl, colIndex, next);
    });

    // Reset sort state when table is replaced
    new MutationObserver(function(mutations) {
        mutations.forEach(function(m) {
            m.addedNodes.forEach(function(n) {
                if (n.nodeType === 1 && n.querySelector && n.querySelector('.mtab-table')) {
                    sortState = {};
                    originalRows = null;
                    currentTable = null;
                }
            });
        });
    }).observe(document.body, { childList: true, subtree: true });
})();
