/* ——— FIFA World Cup live section ——— */
(function () {
    var grid = document.getElementById('wcGrid');
    var tabsEl = document.getElementById('wcTabs');
    var updatedEl = document.getElementById('wcUpdated');
    var statusDot = document.getElementById('wcStatusDot');
    var modal = document.getElementById('wcModal');
    var modalContent = document.getElementById('wcModalContent');
    var modalClose = document.getElementById('wcModalClose');
    if (!grid) return;

    var state = { matches: [], filter: 'all' };

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    function crestHTML(team) {
        if (team.crest) {
            return '<div class="wc-crest"><img src="' + esc(team.crest) +
                '" alt="" loading="lazy" onerror="this.parentNode.innerHTML=\'<span class=&quot;wc-tla&quot;>' +
                esc(team.tla || team.short || '?') + '</span>\'"></div>';
        }
        return '<div class="wc-crest"><span class="wc-tla">' +
            esc(team.tla || team.short || '?') + '</span></div>';
    }

    function statusBadge(m) {
        if (m.live) {
            return '<span class="wc-badge live"><span class="wc-live-dot"></span>' +
                (m.minute ? esc(m.minute) + "'" : 'LIVE') + '</span>';
        }
        if (m.finished) return '<span class="wc-badge ft">Full time</span>';
        return '<span class="wc-badge up">Upcoming</span>';
    }

    function centerHTML(m) {
        if (m.live || m.finished) {
            var h = m.score.home == null ? '–' : m.score.home;
            var a = m.score.away == null ? '–' : m.score.away;
            var html = '<div class="wc-score">' + h + '<span class="sep">:</span>' + a + '</div>';
            if (m.live && m.minute) html += '<div class="wc-minute">' + esc(m.minute) + "'</div>";
            else if (m.live) html += '<div class="wc-minute">LIVE</div>';
            if (m.score.halfHome != null) {
                html += '<div class="wc-half">HT ' + m.score.halfHome + '–' + m.score.halfAway + '</div>';
            }
            return html;
        }
        var t = m.ist || {};
        return '<div class="wc-kickoff">' + esc(t.time || 'TBD') + '</div>' +
            '<div class="wc-ist">IST</div>';
    }

    function cardHTML(m) {
        var stage = m.group ? (m.group.replace('_', ' ')) : (m.stage || '');
        var hasLineups = !!m.lineups;
        return '' +
        '<article class="wc-card' + (m.live ? ' is-live' : '') + '" data-id="' + m.id + '">' +
            '<div class="wc-card-top">' +
                '<span class="wc-stage">' + esc(stage || 'Match') + '</span>' +
                statusBadge(m) +
            '</div>' +
            '<div class="wc-teams">' +
                '<div class="wc-team home">' + crestHTML(m.home) +
                    '<span class="wc-team-name">' + esc(m.home.short) + '</span></div>' +
                '<div class="wc-center">' + centerHTML(m) + '</div>' +
                '<div class="wc-team away">' + crestHTML(m.away) +
                    '<span class="wc-team-name">' + esc(m.away.short) + '</span></div>' +
            '</div>' +
            '<div class="wc-actions">' +
                '<button class="wc-btn wc-lineups-btn"' + (hasLineups ? '' : ' disabled') + '>' +
                    (hasLineups ? 'Line-ups' : 'Line-ups soon') + '</button>' +
            '</div>' +
        '</article>';
    }

    function passesFilter(m) {
        if (state.filter === 'all') return true;
        if (state.filter === 'live') return m.live;
        if (state.filter === 'finished') return m.finished;
        if (state.filter === 'upcoming') return !m.live && !m.finished;
        return true;
    }

    function render() {
        var list = state.matches.filter(passesFilter);
        if (!list.length) {
            grid.innerHTML = '<div class="wc-empty">No matches in this view yet. ' +
                'Fixtures appear here as soon as the schedule syncs.</div>';
            return;
        }
        var html = '', lastDate = null;
        list.forEach(function (m) {
            var d = (m.ist && m.ist.dateLabel) || 'Date TBD';
            if (d !== lastDate) {
                html += '<div class="wc-dateband">' + esc(d) + '</div>';
                lastDate = d;
            }
            html += cardHTML(m);
        });
        grid.innerHTML = html;
    }

    /* ——— lineups modal ——— */
    function rowsFromFormation(formation, starting) {
        if (!starting || !starting.length) return [];
        var gk = [starting[0]];
        var rest = starting.slice(1);
        var rows = [gk];
        var parts = (formation || '').split('-').map(function (n) { return parseInt(n, 10); })
            .filter(function (n) { return n > 0; });
        if (!parts.length) { rows.push(rest); return rows; }
        var idx = 0;
        parts.forEach(function (count) {
            rows.push(rest.slice(idx, idx + count));
            idx += count;
        });
        if (idx < rest.length) rows.push(rest.slice(idx));
        return rows;
    }

    function playerHTML(p) {
        var num = p.number != null ? p.number : '';
        var nm = (p.name || '').split(' ').slice(-1)[0] || p.name || '';
        return '<div class="wc-player"><div class="wc-player-dot">' + esc(num) +
            '</div><div class="wc-player-name">' + esc(nm) + '</div></div>';
    }

    function pitchHTML(side) {
        if (!side || !side.starting || !side.starting.length) {
            return '<div class="wc-nolineup">Starting XI not published yet.</div>';
        }
        var rows = rowsFromFormation(side.formation, side.starting);
        var inner = rows.map(function (row) {
            return '<div class="wc-pitch-row">' + row.map(playerHTML).join('') + '</div>';
        }).join('');
        var html = '<div class="wc-pitch">' + inner + '</div>';
        if (side.formation) html += '<div style="text-align:center"><span class="wc-formation-pill">' + esc(side.formation) + '</span></div>';
        if (side.bench && side.bench.length) {
            html += '<div class="wc-bench"><h4>Substitutes</h4><div class="wc-bench-list">' +
                side.bench.map(function (p) {
                    return '<span class="wc-bench-item"><span>' + esc(p.number != null ? p.number : '') +
                        '</span>' + esc(p.name || '') + '</span>';
                }).join('') + '</div></div>';
        }
        if (side.coach) html += '<div class="wc-coach">Coach · <span>' + esc(side.coach) + '</span></div>';
        return html;
    }

    function openModal(m) {
        if (!m.lineups) return;
        var score = (m.live || m.finished)
            ? '<span class="wc-modal-score"> ' + (m.score.home == null ? '–' : m.score.home) +
              ' : ' + (m.score.away == null ? '–' : m.score.away) + ' </span>'
            : ' vs ';
        var head = '<div class="wc-modal-head">' +
            '<div class="wc-modal-stage">' + esc(m.stage || m.group || 'Match') +
                ' · ' + esc((m.ist && m.ist.label) || '') + '</div>' +
            '<div class="wc-modal-teams">' + esc(m.home.short) + score + esc(m.away.short) + '</div>' +
        '</div>';
        var toggle = '<div class="wc-pitch-toggle">' +
            '<button class="active" data-side="home">' + esc(m.home.short) + '</button>' +
            '<button data-side="away">' + esc(m.away.short) + '</button>' +
        '</div>';
        var pitches = '<div id="wcPitchHome">' + pitchHTML(m.lineups.home) + '</div>' +
            '<div id="wcPitchAway" style="display:none">' + pitchHTML(m.lineups.away) + '</div>';
        modalContent.innerHTML = head + toggle + pitches;

        modalContent.querySelectorAll('.wc-pitch-toggle button').forEach(function (b) {
            b.addEventListener('click', function () {
                modalContent.querySelectorAll('.wc-pitch-toggle button').forEach(function (x) { x.classList.remove('active'); });
                b.classList.add('active');
                var side = b.getAttribute('data-side');
                document.getElementById('wcPitchHome').style.display = side === 'home' ? '' : 'none';
                document.getElementById('wcPitchAway').style.display = side === 'away' ? '' : 'none';
            });
        });
        modal.classList.add('open');
        modal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
    }

    function closeModal() {
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
    }
    if (modalClose) modalClose.addEventListener('click', closeModal);
    if (modal) modal.addEventListener('click', function (e) { if (e.target === modal) closeModal(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeModal(); });

    grid.addEventListener('click', function (e) {
        var btn = e.target.closest('.wc-lineups-btn');
        if (!btn || btn.disabled) return;
        var card = e.target.closest('.wc-card');
        var m = state.matches.find(function (x) { return String(x.id) === card.getAttribute('data-id'); });
        if (m) openModal(m);
    });

    tabsEl.addEventListener('click', function (e) {
        var b = e.target.closest('.wc-tab');
        if (!b) return;
        tabsEl.querySelectorAll('.wc-tab').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
        state.filter = b.getAttribute('data-filter');
        render();
    });

    function setCounts() {
        var c = { all: state.matches.length, live: 0, upcoming: 0, finished: 0 };
        state.matches.forEach(function (m) {
            if (m.live) c.live++; else if (m.finished) c.finished++; else c.upcoming++;
        });
        tabsEl.querySelectorAll('.wc-tab').forEach(function (t) {
            var f = t.getAttribute('data-filter');
            var base = t.textContent.replace(/\s*\d+$/, '').trim();
            t.innerHTML = base + ' <span class="wc-tab-count">' + (c[f] || 0) + '</span>';
        });
        if (statusDot) statusDot.classList.toggle('beat', c.live > 0);
    }

    function load() {
        fetch('wc-data.json?t=' + Date.now(), { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                state.matches = (data.matches || []).slice();
                if (updatedEl) {
                    updatedEl.textContent = data.matches && data.matches.length
                        ? 'Updated ' + (data.updatedLabel || '') + (
                            state.matches.some(function (m) { return m.live; }) ? ' · LIVE NOW' : '')
                        : 'Fixtures sync in progress — check back shortly';
                }
                setCounts();
                render();
            })
            .catch(function () {
                grid.innerHTML = '<div class="wc-empty">Couldn\'t load World Cup data right now.</div>';
            });
    }

    load();
    setInterval(load, 60000);
})();
