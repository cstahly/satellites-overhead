import GObject from 'gi://GObject';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const PASSES = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'share', 'sat-passes', 'passes.json']);

function readPasses() {
    try {
        const [ok, bytes] = GLib.file_get_contents(PASSES);
        if (!ok)
            return [];
        const d = JSON.parse(new TextDecoder().decode(bytes));
        return Array.isArray(d.passes) ? d.passes : [];
    } catch (_e) {
        return [];
    }
}

function fmtDelta(ms) {
    let s = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(s / 3600); s -= h * 3600;
    const m = Math.floor(s / 60); s -= m * 60;
    const pad = n => String(n).padStart(2, '0');
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function shortName(n) {
    return n.replace('METEOR-M2 ', 'M2-').replace('ORBCOMM ', '').replace('ORBCOMM', 'ORBCOMM');
}

const SatButton = GObject.registerClass(
class SatButton extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'Sat Passes');
        this._label = new St.Label({text: '\u{1F6F0} …', y_align: Clutter.ActorAlign.CENTER});
        this.add_child(this._label);
        this._passes = [];

        this.menu.connect('open-state-changed', (_m, open) => {
            if (open)
                this._rebuildMenu();
        });

        this._load();
        this._tickId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            this._tick();
            return GLib.SOURCE_CONTINUE;
        });
        this._loadId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 120, () => {
            this._load();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _load() {
        this._passes = readPasses();
        this._rebuildMenu();
        this._tick();
    }

    _rebuildMenu() {
        this.menu.removeAll();
        const now = Date.now();
        const up = this._passes.filter(p => Date.parse(p.aos) > now).slice(0, 12);
        if (up.length === 0) {
            const item = new PopupMenu.PopupMenuItem('No upcoming passes', {reactive: false});
            this.menu.addMenuItem(item);
            return;
        }
        for (const p of up) {
            const aos = new Date(Date.parse(p.aos));
            const when = aos.toLocaleString([], {weekday: 'short', hour: '2-digit', minute: '2-digit'});
            const txt = `${when}   ${shortName(p.name)}   ${Math.round(p.max_el)}°   in ${fmtDelta(Date.parse(p.aos) - now)}`;
            const item = new PopupMenu.PopupMenuItem(txt, {reactive: false});
            this.menu.addMenuItem(item);
        }
    }

    _tick() {
        const now = Date.now();
        const nxt = this._passes.find(p => Date.parse(p.aos) > now);
        if (nxt)
            this._label.set_text(`\u{1F6F0} ${shortName(nxt.name)} ${Math.round(nxt.max_el)}° ${fmtDelta(Date.parse(nxt.aos) - now)}`);
        else
            this._label.set_text('\u{1F6F0} —');
    }

    destroy() {
        if (this._tickId)
            GLib.source_remove(this._tickId);
        if (this._loadId)
            GLib.source_remove(this._loadId);
        this._tickId = null;
        this._loadId = null;
        super.destroy();
    }
});

export default class SatPassesExtension extends Extension {
    enable() {
        this._btn = new SatButton();
        Main.panel.addToStatusArea('sat-passes', this._btn, 2, 'right');
    }

    disable() {
        if (this._btn) {
            this._btn.destroy();
            this._btn = null;
        }
    }
}
