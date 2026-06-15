use anyhow::Context;
use chrono::{DateTime, Duration, Local, Utc};
use clap::{Parser, Subcommand};
use serde_json::Value;
use std::collections::BTreeSet;
use std::io::{IsTerminal, Write};
extern crate libc;

const DEFAULT_URL: &str = "http://localhost:8723";

// ── colour ────────────────────────────────────────────────────────────────────

fn is_tty() -> bool {
    std::io::stdout().is_terminal()
}

fn colour(code: &str, s: &str) -> String {
    if is_tty() {
        format!("\x1b[{}m{}\x1b[0m", code, s)
    } else {
        s.to_string()
    }
}

fn green(s: &str) -> String  { colour("32", s) }
fn yellow(s: &str) -> String { colour("33", s) }
fn red(s: &str) -> String    { colour("31", s) }
fn bold(s: &str) -> String   { colour("1",  s) }
fn dim(s: &str) -> String    { colour("2",  s) }
fn cyan(s: &str) -> String   { colour("36", s) }

// ── formatting ────────────────────────────────────────────────────────────────

fn fmt_dur(secs: f64) -> String {
    let secs = secs as i64;
    let h = secs / 3600;
    let m = (secs % 3600) / 60;
    let s = secs % 60;
    if h > 0 { format!("{}h{:02}m", h, m) }
    else if m > 0 { format!("{}m{:02}s", m, s) }
    else { format!("{}s", s) }
}

fn fmt_bytes(n: f64) -> String {
    const UNITS: &[&str] = &["B", "KB", "MB", "GB"];
    let mut v = n;
    let mut i = 0;
    while v >= 1024.0 && i < UNITS.len() - 1 {
        v /= 1024.0;
        i += 1;
    }
    if i == 0 { format!("{} B", v as u64) }
    else { format!("{:.1} {}", v, UNITS[i]) }
}

fn fmt_el(el: f64) -> String {
    let s = format!("{:.1}°", el);
    if el >= 45.0 { green(&s) }
    else if el >= 20.0 { yellow(&s) }
    else { dim(&s) }
}
fn fmt_el_opt(v: &serde_json::Value) -> String {
    match v.as_f64() {
        Some(el) => fmt_el(el),
        None     => dim("—"),
    }
}

fn parse_dt(s: &str) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(&s.replace('Z', "+00:00"))
        .map(|d| d.with_timezone(&Utc))
        .ok()
}

fn fmt_local(iso: &str) -> String {
    parse_dt(iso)
        .map(|d| d.with_timezone(&Local).format("%m-%d %H:%M").to_string())
        .unwrap_or_else(|| iso.to_string())
}

fn time_until(iso: &str) -> String {
    let Some(dt) = parse_dt(iso) else { return String::new() };
    let delta = dt.signed_duration_since(Utc::now());
    if delta < Duration::zero() {
        dim("now")
    } else {
        cyan(&format!("in {}", fmt_dur(delta.num_seconds() as f64)))
    }
}

// ── table ─────────────────────────────────────────────────────────────────────

fn col_widths(headers: &[&str], rows: &[Vec<String>]) -> Vec<usize> {
    let mut w: Vec<usize> = headers.iter().map(|h| h.len()).collect();
    for row in rows {
        for (i, cell) in row.iter().enumerate() {
            // strip ANSI codes for width calculation
            let visible: String = {
                let mut out = String::new();
                let mut in_escape = false;
                for c in cell.chars() {
                    if c == '\x1b' { in_escape = true; }
                    else if in_escape { if c == 'm' { in_escape = false; } }
                    else { out.push(c); }
                }
                out
            };
            if i < w.len() { w[i] = w[i].max(visible.len()); }
        }
    }
    w
}

fn print_table<W: Write>(out: &mut W, headers: &[&str], rows: &[Vec<String>]) {
    if rows.is_empty() {
        let _ = writeln!(out, "{}", dim("  (no results)"));
        return;
    }
    let widths = col_widths(headers, rows);
    let header_row: Vec<String> = headers.iter().enumerate()
        .map(|(i, h)| format!("{:<width$}", h, width = widths[i]))
        .collect();
    let _ = writeln!(out, "  {}", bold(&header_row.join("  ")));
    let sep: Vec<String> = widths.iter().map(|&n| "-".repeat(n)).collect();
    let _ = writeln!(out, "{}", dim(&format!("  {}", sep.join("  "))));
    for row in rows {
        let cells: Vec<String> = row.iter().enumerate().map(|(i, cell)| {
            let visible_len: usize = {
                let mut len = 0;
                let mut in_escape = false;
                for c in cell.chars() {
                    if c == '\x1b' { in_escape = true; }
                    else if in_escape { if c == 'm' { in_escape = false; } }
                    else { len += 1; }
                }
                len
            };
            let pad = if i < widths.len() && widths[i] > visible_len { widths[i] - visible_len } else { 0 };
            format!("{}{}", cell, " ".repeat(pad))
        }).collect();
        let _ = writeln!(out, "  {}", cells.join("  "));
    }
}

// ── HTTP ──────────────────────────────────────────────────────────────────────

fn summarize_body(body: &str) -> String {
    let mut out = String::new();
    let mut in_tag = false;
    let mut last_space = false;
    for c in body.chars() {
        match c {
            '<' => in_tag = true,
            '>' => {
                in_tag = false;
                if !last_space {
                    out.push(' ');
                    last_space = true;
                }
            }
            _ if in_tag => {}
            _ if c.is_whitespace() => {
                if !last_space {
                    out.push(' ');
                    last_space = true;
                }
            }
            _ => {
                out.push(c);
                last_space = false;
            }
        }
    }
    let trimmed = out.trim();
    let shortened: String = trimmed.chars().take(240).collect();
    if shortened.len() < trimmed.len() {
        format!("{}...", shortened)
    } else if trimmed.is_empty() {
        "(empty response)".to_string()
    } else {
        trimmed.to_string()
    }
}

fn response_text(response: reqwest::blocking::Response, url: &str) -> anyhow::Result<String> {
    let status = response.status();
    let text = response
        .text()
        .with_context(|| format!("could not read response body from {}", url))?;
    if !status.is_success() {
        anyhow::bail!("{} returned {}: {}", url, status, summarize_body(&text));
    }
    Ok(text)
}

fn get(client: &reqwest::blocking::Client, url: &str) -> anyhow::Result<Value> {
    let response = client
        .get(url)
        .send()
        .with_context(|| format!("GET {} failed", url))?;
    let text = response_text(response, url)?;
    serde_json::from_str(&text)
        .with_context(|| format!("error decoding JSON from {}: {}", url, summarize_body(&text)))
}

fn get_text(client: &reqwest::blocking::Client, url: &str) -> anyhow::Result<String> {
    let response = client
        .get(url)
        .send()
        .with_context(|| format!("GET {} failed", url))?;
    response_text(response, url)
}

fn post(client: &reqwest::blocking::Client, url: &str, body: &Value) -> anyhow::Result<Value> {
    let response = client
        .post(url)
        .json(body)
        .send()
        .with_context(|| format!("POST {} failed", url))?;
    let text = response_text(response, url)?;
    serde_json::from_str(&text)
        .with_context(|| format!("error decoding JSON from {}: {}", url, summarize_body(&text)))
}

#[allow(dead_code)]
fn delete_req(client: &reqwest::blocking::Client, url: &str) -> anyhow::Result<Value> {
    let response = client
        .delete(url)
        .send()
        .with_context(|| format!("DELETE {} failed", url))?;
    let text = response_text(response, url)?;
    serde_json::from_str(&text)
        .with_context(|| format!("error decoding JSON from {}: {}", url, summarize_body(&text)))
}

fn rule_pass_targets(client: &reqwest::blocking::Client, base: &str) -> anyhow::Result<Vec<(u32, String)>> {
    let data = get(client, &format!("{}/scheduler/rules", base))?;
    let rules = data
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("unexpected /scheduler/rules response"))?;
    let mut targets = BTreeSet::new();
    for rule in rules {
        let Some(norad) = rule["norad"].as_u64() else { continue; };
        if norad == 0 || norad > u32::MAX as u64 { continue; }
        let group = rule["group"].as_str().unwrap_or("radio").to_string();
        targets.insert((norad as u32, group));
    }
    if targets.is_empty() {
        targets.insert((59051, "radio".to_string()));
    }
    Ok(targets.into_iter().collect())
}

fn pass_url(
    base: &str,
    norad: u32,
    group: &str,
    hours: f64,
    min_el: f64,
    start: Option<&str>,
) -> String {
    let mut url = format!(
        "{}/passes?lat=40.42&lon=-86.88&alt_m=180&hours={}&min_el={}&group={}&track_step_s=60&norad={}",
        base, hours, min_el, group, norad,
    );
    if let Some(value) = start {
        url.push_str("&start=");
        url.push_str(value);
    }
    url
}

fn fetch_passes_for_targets(
    client: &reqwest::blocking::Client,
    base: &str,
    targets: &[(u32, String)],
    hours: f64,
    min_el: f64,
    start: Option<&str>,
) -> anyhow::Result<Vec<Value>> {
    let mut passes = Vec::new();
    for (norad, group) in targets {
        let url = pass_url(base, *norad, group, hours, min_el, start);
        let data = get(client, &url)
            .with_context(|| format!("could not fetch passes for NORAD {}", norad))?;
        let arr = data
            .as_array()
            .ok_or_else(|| anyhow::anyhow!("unexpected /passes response for NORAD {}", norad))?;
        passes.extend(arr.iter().cloned());
    }
    passes.sort_by_key(|p| p["aos"].as_str().unwrap_or("").to_string());
    Ok(passes)
}

fn fetch_upcoming_windows(
    client: &reqwest::blocking::Client,
    base: &str,
    hours: f64,
) -> anyhow::Result<Vec<Value>> {
    let url = format!("{}/scheduler/upcoming?hours={}&limit_per_rule=100", base, hours);
    let data = get(client, &url)?;
    let arr = data
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("unexpected /scheduler/upcoming response"))?;
    Ok(arr.iter().cloned().collect())
}

// ── CLI definition ────────────────────────────────────────────────────────────

#[derive(Parser)]
#[command(name = "sdr", about = "Satellite SDR scheduler CLI", version)]
#[command(arg_required_else_help = false)]
struct Cli {
    #[arg(long, default_value = DEFAULT_URL, global = true)]
    url: String,
    #[arg(long, global = true, help = "Raw JSON output")]
    json: bool,
    #[arg(short = 'c', global = true, value_name = "N", help = "Number of passes to show (default: all in 48h)")]
    count: Option<usize>,
    #[arg(short = 'w', long, global = true, help = "Keep running and refresh on interval")]
    watch: bool,
    #[arg(short = 'i', long, global = true, value_name = "SECS", default_value_t = 5, help = "Refresh interval for --watch (seconds)")]
    interval: u64,
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    /// Scheduler status and next job
    Status,
    /// Satellites overhead right now
    Overhead {
        #[arg(long, default_value_t = 10.0)]
        min_el: f64,
    },
    /// Upcoming passes
    Passes {
        #[arg(long)]
        norad: Option<u32>,
        #[arg(long, default_value_t = 24.0)]
        hours: f64,
        #[arg(long, default_value_t = 10.0)]
        min_el: f64,
    },
    /// List scheduler rules
    Rules,
    /// Enable or disable a rule
    Rule {
        action: RuleAction,
        id: String,
    },
    /// Capture history
    Captures {
        #[arg(long)]
        norad: Option<u32>,
        #[arg(long, default_value_t = 20)]
        limit: usize,
    },
    /// Queue an immediate capture
    Scan {
        norad: u32,
        #[arg(long, default_value_t = 300)]
        duration: u32,
    },
    /// Show diagnostic report for a capture
    Report {
        capture_id: String,
    },
    /// Show log paths and tail recent entries
    Logs {
        #[arg(long, default_value_t = 20, help = "Lines to show per log")]
        tail: usize,
    },
}

#[derive(Clone, clap::ValueEnum)]
enum RuleAction { Enable, Disable }

// ── log helpers ───────────────────────────────────────────────────────────────

fn tail_lines(path: &str, n: usize) -> Vec<String> {
    let Ok(content) = std::fs::read_to_string(path) else { return vec![]; };
    content.lines().rev().take(n).map(String::from).collect::<Vec<_>>()
        .into_iter().rev().collect()
}

struct SignalSample {
    snr: f64,
    peak_snr: f64,
    viterbi: String,
    ber: f64,
    deframer: String,
}

fn parse_latest_signal(log_path: &str) -> Option<SignalSample> {
    let content = std::fs::read_to_string(log_path).ok()?;
    let lines: Vec<&str> = content.lines().collect();
    // Walk backwards looking for paired SNR + BER lines
    let mut i = lines.len();
    while i >= 2 {
        i -= 1;
        let snr_line = lines[i];
        if !snr_line.contains("SNR :") { continue; }
        // Look for the BER line nearby (usually next line, sometimes same)
        let ber_line = if i + 1 < lines.len() && lines[i+1].contains("Viterbi") {
            lines[i+1]
        } else if snr_line.contains("Viterbi") {
            snr_line
        } else {
            continue;
        };

        let snr = snr_line.split("SNR :").nth(1)
            .and_then(|s| s.trim().split("dB").next())
            .and_then(|s| s.trim().parse::<f64>().ok())?;
        let peak_snr = snr_line.split("Peak SNR:").nth(1)
            .and_then(|s| s.trim().split("dB").next())
            .and_then(|s| s.trim().parse::<f64>().ok())
            .unwrap_or(snr);
        let viterbi = if ber_line.contains("SYNCED") { "SYNCED".to_string() }
                      else if ber_line.contains("NOSYNC") { "NOSYNC".to_string() }
                      else { "—".to_string() };
        let ber = ber_line.split("BER :").nth(1)
            .and_then(|s| s.trim().split(',').next())
            .and_then(|s| s.trim().parse::<f64>().ok())
            .unwrap_or(0.0);
        let deframer = if ber_line.contains("Deframer : SYNCED") { "SYNCED".to_string() }
                       else if ber_line.contains("Deframer : NOSYNC") { "NOSYNC".to_string() }
                       else { "—".to_string() };

        return Some(SignalSample { snr, peak_snr, viterbi, ber, deframer });
    }
    None
}

fn print_signal<W: Write>(w: &mut W, s: &SignalSample) {
    let snr_str = {
        let v = format!("{:.1} dB", s.snr);
        if s.snr >= 15.0 { green(&v) } else if s.snr >= 8.0 { yellow(&v) } else { red(&v) }
    };
    let ber_str = format!("{:.4}", s.ber);
    let deframer_str = if s.deframer == "SYNCED" { green("SYNCED") } else { red(&s.deframer) };
    let viterbi_str = if s.viterbi == "SYNCED" { green("SYNCED") } else { yellow(&s.viterbi) };
    let _ = writeln!(w, "  Signal     SNR {} (peak {:.1} dB)  Viterbi {}  BER {}  Deframer {}",
        snr_str, s.peak_snr, viterbi_str, dim(&ber_str), deframer_str);
}

// ── command handlers ──────────────────────────────────────────────────────────

fn cmd_status<W: Write>(w: &mut W, client: &reqwest::blocking::Client, base: &str, as_json: bool) -> anyhow::Result<()> {
    let data = get(client, &format!("{}/scheduler/status", base))?;
    if as_json { println!("{}", serde_json::to_string_pretty(&data)?); return Ok(()); }

    let state = data["state"].as_str().unwrap_or("unknown");
    let live = data["live"].as_bool().unwrap_or(false);
    let state_str = if live { green("running") } else if state == "idle" { yellow("idle") } else { red(state) };
    let age = data["status_age_s"].as_f64();
    let age_str = age.map(|a| dim(&format!("  updated {}s ago", a as u64))).unwrap_or_default();

    let _ = writeln!(w, "\n  Scheduler  {}{}", state_str, age_str);
    let _ = writeln!(w, "  Queue      {} command(s) pending", data["queue_count"].as_u64().unwrap_or(0));

    if let Some(job) = data["current_job"].as_object() {
        let label = job.get("label").and_then(|v| v.as_str()).unwrap_or("—");
        let msg = data["message"].as_str().unwrap_or("");
        if live {
            let freq = job.get("frequency_hz").and_then(|v| v.as_f64());
            let freq_str = freq.map(|f| format!("  {:.3} MHz", f / 1e6)).unwrap_or_default();
            let output = job.get("output").and_then(|v| v.as_str()).unwrap_or("");
            let lna = job.get("lna_gain").and_then(|v| v.as_i64()).map(|v| v.to_string()).unwrap_or_else(|| "—".to_string());
            let vga = job.get("vga_gain").and_then(|v| v.as_i64()).map(|v| v.to_string()).unwrap_or_else(|| "—".to_string());
            let amp = job.get("amp").and_then(|v| v.as_i64()).map(|v| v.to_string()).unwrap_or_else(|| "—".to_string());
            let _ = writeln!(w, "  Job        {}{}", bold(label), freq_str);
            let _ = writeln!(w, "  Gains      LNA={}  VGA={}  amp={}", lna, vga, amp);
            if let Some(fire) = job.get("fire_time").and_then(|v| v.as_str()) {
                if let Some(dur) = job.get("duration_s").and_then(|v| v.as_f64()) {
                    if let Some(start) = parse_dt(fire) {
                        let end = start + Duration::seconds(dur as i64);
                        let end_local = end.with_timezone(&Local).format("%H:%M:%S").to_string();
                        let remaining = (end - Utc::now()).num_seconds();
                        let rem_str = if remaining > 0 {
                            cyan(&format!("{} remaining", fmt_dur(remaining as f64)))
                        } else {
                            dim("finishing...")
                        };
                        let _ = writeln!(w, "  Runs until {}  {}", bold(&end_local), rem_str);
                    }
                }
            }
            if !output.is_empty() {
                let log_path = format!("{}.log", output);
                let _ = writeln!(w, "  Log        {}", dim(&log_path));
                if let Some(sig) = parse_latest_signal(&log_path) {
                    print_signal(w, &sig);
                } else {
                    let _ = writeln!(w, "  Signal     {}", dim("no samples yet — capture may be starting"));
                }
            }
        } else {
            let fire = job.get("fire_time").and_then(|v| v.as_str()).unwrap_or("");
            let local = if fire.is_empty() { "—".to_string() } else { fmt_local(fire) };
            let until = if fire.is_empty() { String::new() } else { time_until(fire) };
            let _ = writeln!(w, "  Next       {}  {}  {}", bold(label), local, until);
        }
        if !msg.is_empty() { let _ = writeln!(w, "  Status     {}", dim(msg)); }
    }
    let _ = writeln!(w);
    Ok(())
}

fn cmd_logs(client: &reqwest::blocking::Client, base: &str, tail: usize) -> anyhow::Result<()> {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/root".to_string());
    let sched_log = format!("{}/sdr_scheduler.log", home);

    let data = get(client, &format!("{}/scheduler/status", base))?;
    let live = data["live"].as_bool().unwrap_or(false);
    let satdump_log = data["current_job"].as_object()
        .and_then(|j| j.get("output"))
        .and_then(|v| v.as_str())
        .map(|out| format!("{}.log", out));

    println!("\n  {}", bold("Log files"));
    println!("  Scheduler  {}", cyan(&sched_log));
    if let Some(ref p) = satdump_log {
        println!("  SatDump    {}", cyan(p));
    }
    println!("\n  {} tail -f {}", dim("follow:"), sched_log);
    if let Some(ref p) = satdump_log {
        println!("  {}         tail -f {}", dim("       "), p);
    }

    println!("\n{}", bold(&format!("  ── scheduler log (last {}) ──────────────────────────", tail)));
    let sched_lines = tail_lines(&sched_log, tail);
    if sched_lines.is_empty() {
        println!("{}", dim("  (empty or not found)"));
    } else {
        for line in &sched_lines {
            println!("  {}", dim(line));
        }
    }

    if live {
        if let Some(ref log_path) = satdump_log {
            println!("\n{}", bold(&format!("  ── satdump signal (last {}) ──────────────────────────", tail)));
            // Show only signal-relevant lines
            let content = std::fs::read_to_string(log_path).unwrap_or_default();
            let signal_lines: Vec<&str> = content.lines()
                .filter(|l| l.contains("SNR") || l.contains("Viterbi") || l.contains("Deframer")
                         || l.contains("SYNCED") || l.contains("NOSYNC") || l.contains("Timeout"))
                .collect();
            let show = &signal_lines[signal_lines.len().saturating_sub(tail)..];
            if show.is_empty() {
                println!("{}", dim("  (no signal lines yet)"));
            } else {
                for line in show {
                    // strip ANSI escape codes from satdump's coloured output
                    let clean: String = {
                        let mut out = String::new();
                        let mut in_esc = false;
                        for c in line.chars() {
                            if c == '\x1b' { in_esc = true; }
                            else if in_esc { if c == 'm' { in_esc = false; } }
                            else { out.push(c); }
                        }
                        out
                    };
                    // colour the line based on content
                    let formatted = if clean.contains("Deframer : SYNCED") { green(&clean) }
                                    else if clean.contains("NOSYNC") { yellow(&clean) }
                                    else { dim(&clean) };
                    println!("  {}", formatted);
                }
            }

            if let Some(sig) = parse_latest_signal(log_path) {
                println!();
                print_signal(&mut std::io::stdout(), &sig);
            }
        }
    }

    println!();
    Ok(())
}

fn cmd_overhead<W: Write>(w: &mut W, client: &reqwest::blocking::Client, base: &str, min_el: f64, as_json: bool) -> anyhow::Result<()> {
    let start = (Utc::now() - Duration::hours(2)).format("%Y-%m-%dT%H:%M:%SZ").to_string();
    let targets = rule_pass_targets(client, base)?;
    let passes = fetch_passes_for_targets(client, base, &targets, 2.5, min_el, Some(&start))?;

    let now_ts = Utc::now().timestamp() as f64;
    let overhead: Vec<&Value> = passes.iter().filter(|p| {
        let aos = p["aos"].as_str().and_then(|s| parse_dt(s)).map(|d| d.timestamp() as f64).unwrap_or(f64::MAX);
        let los = p["los"].as_str().and_then(|s| parse_dt(s)).map(|d| d.timestamp() as f64).unwrap_or(0.0);
        aos <= now_ts && now_ts <= los
    }).collect();
    if as_json { println!("{}", serde_json::to_string_pretty(&overhead)?); return Ok(()); }

    if overhead.is_empty() {
        let _ = writeln!(w, "{}", dim("  Nothing above the horizon right now."));
        return Ok(());
    }
    let _ = writeln!(w);
    let rows: Vec<Vec<String>> = overhead.iter().map(|p| {
        let los_ts = p["los"].as_str().and_then(|s| parse_dt(s)).map(|d| d.timestamp() as f64).unwrap_or(now_ts);
        let remaining = los_ts - now_ts;
        vec![
            p["name"].as_str().unwrap_or("—").to_string(),
            p["norad"].to_string(),
            fmt_el(p["max_el"].as_f64().unwrap_or(0.0)),
            cyan(&format!("LOS in {}", fmt_dur(remaining))),
        ]
    }).collect();
    print_table(w, &["Satellite", "NORAD", "Max El", ""], &rows);
    let _ = writeln!(w);
    Ok(())
}

fn cmd_passes(client: &reqwest::blocking::Client, base: &str, norad: Option<u32>, hours: f64, min_el: f64, as_json: bool) -> anyhow::Result<()> {
    let mut passes = if let Some(n) = norad {
        fetch_passes_for_targets(client, base, &[(n, "radio".to_string())], hours, min_el, None)?
    } else {
        fetch_upcoming_windows(client, base, hours)?
    };
    if norad.is_none() {
        passes.retain(|p| p["max_el"].as_f64().unwrap_or(0.0) >= min_el);
    }
    if as_json { println!("{}", serde_json::to_string_pretty(&passes)?); return Ok(()); }

    if passes.is_empty() { println!("{}", dim("  No passes found.")); return Ok(()); }
    println!();
    let rows: Vec<Vec<String>> = passes.iter().map(|p| {
        let start = p["fire_time"].as_str().or_else(|| p["aos"].as_str());
        let mut duration = fmt_dur(p["duration_s"].as_f64().unwrap_or(0.0));
        if p["partial"].as_bool().unwrap_or(false) {
            duration = format!("{} partial", duration);
        }
        vec![
            p["name"].as_str().unwrap_or("—").to_string(),
            p["norad"].to_string(),
            start.map(fmt_local).unwrap_or_else(|| "—".to_string()),
            start.map(time_until).unwrap_or_default(),
            fmt_el(p["max_el"].as_f64().unwrap_or(0.0)),
            duration,
        ]
    }).collect();
    print_table(&mut std::io::stdout(), &["Satellite", "NORAD", "Start (local)", "Until", "Max El", "Duration"], &rows);
    println!();
    Ok(())
}

fn cmd_rules<W: Write>(w: &mut W, client: &reqwest::blocking::Client, base: &str, as_json: bool) -> anyhow::Result<()> {
    let data = get(client, &format!("{}/scheduler/rules", base))?;
    if as_json { println!("{}", serde_json::to_string_pretty(&data)?); return Ok(()); }

    let rules = data.as_array().map(|a| a.as_slice()).unwrap_or(&[]);
    if rules.is_empty() { let _ = writeln!(w, "{}", dim("  No rules configured.")); return Ok(()); }

    // Fetch upcoming runs and index by rule_id
    let (upcoming_arr, upcoming_error) = match get(
        client,
        &format!("{}/scheduler/upcoming?hours=48&limit_per_rule=1", base),
    ) {
        Ok(upcoming) => match upcoming.as_array() {
            Some(runs) => (runs.clone(), None),
            None => (Vec::new(), Some("unexpected non-array response".to_string())),
        },
        Err(error) => (Vec::new(), Some(error.to_string())),
    };
    let mut next_by_rule: std::collections::HashMap<&str, &Value> = std::collections::HashMap::new();
    for run in &upcoming_arr {
        if let Some(id) = run["rule_id"].as_str() {
            next_by_rule.entry(id).or_insert(run);
        }
    }

    // Sort rules by next fire time, rules with no predicted pass go last
    let mut rules_sorted: Vec<&Value> = rules.iter().collect();
    rules_sorted.sort_by_key(|r| {
        let id = r["id"].as_str().unwrap_or("—");
        next_by_rule.get(id)
            .and_then(|run| run["fire_time"].as_str())
            .map(|s| s.to_string())
            .unwrap_or_else(|| "9999".to_string())
    });

    let _ = writeln!(w);
    let rows: Vec<Vec<String>> = rules_sorted.iter().map(|r| {
        let id = r["id"].as_str().unwrap_or("—");
        let enabled = if r["enabled"].as_bool().unwrap_or(false) { green("yes") } else { red("no") };
        let freq = r["frequency_hz"].as_f64().map(|f| format!("{:.3}", f / 1e6)).unwrap_or_else(|| "—".to_string());
        let profile_short = match r["profile"].as_str().unwrap_or("—") {
            "meteor_lrpt_hackrf" => "lrpt",
            "raw_iq_hackrf"      => "raw_iq",
            "satdump_hackrf"     => "satdump",
            other                => other,
        }.to_string();
        let gains = format!("L{}/V{}/A{}",
            r["lna_gain"].as_i64().unwrap_or(0),
            r["vga_gain"].as_i64().unwrap_or(0),
            r["amp"].as_i64().unwrap_or(0));
        let (fire_str, end_str, max_el_str) = if let Some(run) = next_by_rule.get(id) {
            if run["prediction_error"].is_string() {
                (yellow("prediction unavailable"), String::new(), "—".to_string())
            } else {
                let fire = run["fire_time"].as_str().map(|s| {
                    format!("{} {}", fmt_local(s), time_until(s))
                }).unwrap_or_else(|| "—".to_string());
                let end = run["end_time"].as_str().map(fmt_local).unwrap_or_else(|| "—".to_string());
                let el = run["max_el"].as_f64().map(|e| fmt_el(e)).unwrap_or_else(|| "—".to_string());
                (fire, end, el)
            }
        } else if upcoming_error.is_some() {
            (yellow("prediction unavailable"), String::new(), "—".to_string())
        } else {
            (dim("no passes predicted"), String::new(), "—".to_string())
        };
        vec![
            r["name"].as_str().unwrap_or("—").to_string(),
            enabled,
            freq,
            profile_short,
            gains,
            max_el_str,
            fire_str,
            end_str,
        ]
    }).collect();
    if let Some(error) = upcoming_error {
        eprintln!(
            "{}",
            yellow(&format!("  Warning: could not load upcoming predictions: {}", error))
        );
    }
    print_table(w, &["Satellite", "On", "MHz", "Profile", "Gains", "Max El", "Next fire", "Window end"], &rows);
    let _ = writeln!(w);
    Ok(())
}

fn cmd_rule_toggle(client: &reqwest::blocking::Client, base: &str, id: &str, enable: bool) -> anyhow::Result<()> {
    let data = get(client, &format!("{}/scheduler/rules", base))?;
    let rules = data.as_array().ok_or_else(|| anyhow::anyhow!("unexpected response"))?;
    let mut rule = rules.iter()
        .find(|r| r["id"].as_str() == Some(id))
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("Rule '{}' not found", id))?;
    rule["enabled"] = Value::Bool(enable);
    post(client, &format!("{}/scheduler/rules", base), &rule)?;
    let state = if enable { green("enabled") } else { red("disabled") };
    println!("  Rule {} {}.", bold(id), state);
    Ok(())
}

fn cmd_captures(client: &reqwest::blocking::Client, base: &str, norad: Option<u32>, limit: usize, as_json: bool) -> anyhow::Result<()> {
    let mut url = format!("{}/captures", base);
    if let Some(n) = norad { url.push_str(&format!("?norad={}", n)); }
    let data = get(client, &url)?;
    if as_json { println!("{}", serde_json::to_string_pretty(&data)?); return Ok(()); }

    let captures = data.as_array().map(|a| a.as_slice()).unwrap_or(&[]);
    let captures = &captures[..captures.len().min(limit)];
    if captures.is_empty() { println!("{}", dim("  No captures recorded yet.")); return Ok(()); }
    println!();
    let rows: Vec<Vec<String>> = captures.iter().map(|c| {
        let cadu = c["cadu_bytes"].as_f64().unwrap_or(0.0);
        let cadu_str = if cadu > 0.0 { green(&fmt_bytes(cadu)) } else { dim("no lock") };
        let dur = match (c["started_at"].as_str(), c["ended_at"].as_str()) {
            (Some(a), Some(b)) => {
                let da = parse_dt(a).map(|d| d.timestamp()).unwrap_or(0);
                let db = parse_dt(b).map(|d| d.timestamp()).unwrap_or(0);
                fmt_dur((db - da) as f64)
            }
            _ => "—".to_string(),
        };
        let report = if c["report_path"].is_string() { "yes".to_string() } else { dim("—") };
        let id = c["id"].as_str().unwrap_or("").chars().take(8).collect::<String>();
        vec![
            c["started_at"].as_str().map(fmt_local).unwrap_or_else(|| "—".to_string()),
            c["name"].as_str().unwrap_or("—").to_string(),
            c["profile"].as_str().unwrap_or("—").to_string(),
            dur,
            fmt_bytes(c["size_bytes"].as_f64().unwrap_or(0.0)),
            cadu_str,
            report,
            dim(&id),
        ]
    }).collect();
    print_table(&mut std::io::stdout(), &["Time", "Satellite", "Profile", "Duration", "Size", "CADU", "Report", "ID"], &rows);
    println!();
    Ok(())
}

fn cmd_scan(client: &reqwest::blocking::Client, base: &str, norad: u32, duration: u32) -> anyhow::Result<()> {
    let settings = get(client, &format!("{}/capture-settings?norad={}", base, norad))?;
    let name = get(client, &format!("{}/satellite?norad={}", base, norad))
        .ok()
        .and_then(|v| v["name"].as_str().map(String::from))
        .unwrap_or_else(|| format!("NORAD {}", norad));

    let freq = settings["frequency_hz"].as_f64().unwrap_or(0.0);
    println!("\n  Queuing scan for {} (NORAD {})", bold(&name), norad);
    println!("  Frequency  {:.3} MHz", freq / 1e6);
    println!("  Profile    {}", settings["profile"].as_str().unwrap_or("—"));
    println!("  Gains      LNA={} VGA={} amp={}", settings["lna_gain"], settings["vga_gain"], settings["amp"]);
    println!("  Duration   {}", fmt_dur(duration as f64));

    let payload = serde_json::json!({ "norad": norad, "name": name, "duration_s": duration });
    let result = post(client, &format!("{}/scheduler/scan-now", base), &payload)?;
    let cmd_id = result["command"]["id"].as_str().unwrap_or("—");
    println!("\n  {}  command id: {}\n", green("Queued"), dim(cmd_id));
    Ok(())
}

fn resolve_capture_id(client: &reqwest::blocking::Client, base: &str, id_or_prefix: &str) -> anyhow::Result<String> {
    if id_or_prefix.len() == 36 {
        return Ok(id_or_prefix.to_string());
    }
    let data = get(client, &format!("{}/captures", base))?;
    let captures = data.as_array().ok_or_else(|| anyhow::anyhow!("unexpected response"))?;
    let matched: Vec<&str> = captures.iter()
        .filter_map(|c| c["id"].as_str())
        .filter(|id| id.starts_with(id_or_prefix))
        .collect();
    match matched.len() {
        0 => anyhow::bail!("no capture found with id starting '{}'", id_or_prefix),
        1 => Ok(matched[0].to_string()),
        n => anyhow::bail!("{} captures match prefix '{}' — be more specific", n, id_or_prefix),
    }
}

fn cmd_report(client: &reqwest::blocking::Client, base: &str, capture_id: &str) -> anyhow::Result<()> {
    let full_id = resolve_capture_id(client, base, capture_id)?;
    let text = get_text(client, &format!("{}/captures/{}/report", base, &full_id))?;
    println!("{}", text);
    Ok(())
}

// ── dashboard (default, no subcommand) ───────────────────────────────────────

fn cmd_dashboard<W: Write>(w: &mut W, client: &reqwest::blocking::Client, base: &str, count: Option<usize>) -> anyhow::Result<()> {
    let status = get(client, &format!("{}/scheduler/status", base))?;
    let live = status["live"].as_bool().unwrap_or(false);

    let _ = writeln!(w);

    // ── Now running ────────────────────────────────────────────────────────────
    if live {
        if let Some(job) = status["current_job"].as_object() {
            let label = job.get("label").and_then(|v| v.as_str()).unwrap_or("—");
            let freq = job.get("frequency_hz").and_then(|v| v.as_f64())
                .map(|f| format!("  {:.3} MHz", f / 1e6)).unwrap_or_default();
            let remaining = job.get("fire_time").and_then(|v| v.as_str())
                .and_then(|ft| job.get("duration_s").and_then(|v| v.as_f64()).map(|dur| (ft, dur)))
                .and_then(|(ft, dur)| parse_dt(ft).map(|start| {
                    let end = start + Duration::seconds(dur as i64);
                    let secs = (end - Utc::now()).num_seconds();
                    if secs > 0 { cyan(&format!("{} remaining", fmt_dur(secs as f64))) }
                    else { dim("finishing...") }
                }))
                .unwrap_or_default();
            let _ = writeln!(w, "  {}  {}{} {}", bold("NOW "), green(label), freq, remaining);
        }
    } else {
        let _ = writeln!(w, "  {}  {}", bold("NOW "), dim("idle"));
    }

    // ── Recent runs ────────────────────────────────────────────────────────────
    let captures_data = get(client, &format!("{}/captures", base)).unwrap_or(serde_json::json!([]));
    if let Some(all_captures) = captures_data.as_array() {
        let recent: Vec<_> = match count {
            Some(n) => all_captures.iter().take(n).collect(),
            None    => all_captures.iter().take(5).collect(),
        };
        let recent: Vec<_> = recent.into_iter().rev().collect();
        if !recent.is_empty() {
            let _ = writeln!(w, "\n  {}\n", bold("Recent"));
            let rows: Vec<Vec<String>> = recent.iter().map(|c| {
                let name = c["name"].as_str().unwrap_or("—").to_string();
                let time = c["started_at"].as_str().map(fmt_local).unwrap_or_else(|| "—".to_string());
                let el = fmt_el_opt(&c["max_el"]);
                let dur = fmt_dur(c["ended_at"].as_str()
                    .and_then(|e| c["started_at"].as_str().map(|s| (s, e)))
                    .and_then(|(s, e)| parse_dt(s).and_then(|st| parse_dt(e).map(|en| (en - st).num_seconds().max(0) as f64)))
                    .unwrap_or_else(|| c["duration_s"].as_f64().unwrap_or(0.0)));
                let cadu = c["cadu_bytes"].as_f64().unwrap_or(0.0);
                let result_str = if cadu > 0.0 { green(&format!("decoded  {}", fmt_bytes(cadu))) }
                                 else { dim("no lock") };
                vec![name, time, el, dur, result_str]
            }).collect();
            print_table(w, &["Satellite", "Start (local)", "Max El", "Duration", "Result"], &rows);
        }
    }

    // ── Upcoming passes ────────────────────────────────────────────────────────
    let mut windows = fetch_upcoming_windows(client, base, 48.0)?;
    let now_utc = Utc::now();
    windows.retain(|p| {
        p["fire_time"].as_str()
            .or_else(|| p["aos"].as_str())
            .and_then(|s| parse_dt(s))
            .map(|dt| dt > now_utc)
            .unwrap_or(true)
    });
    windows.truncate(count.unwrap_or(10));

    if windows.is_empty() {
        let _ = writeln!(w, "\n{}", dim("  No passes scheduled in the next 48 hours."));
    } else {
        let now_local = Local::now();
        let _ = writeln!(w, "\n  {} {} – {}\n",
            bold("Upcoming"),
            now_local.format("%a %b %d"),
            (now_local + chrono::Duration::days(1)).format("%a %b %d"),
        );
        let rows: Vec<Vec<String>> = windows.iter().map(|p| {
            let start = p["fire_time"].as_str().or_else(|| p["aos"].as_str());
            let mut duration = fmt_dur(p["duration_s"].as_f64().unwrap_or(0.0));
            if p["partial"].as_bool().unwrap_or(false) {
                duration = format!("{} partial", duration);
            }
            vec![
                p["name"].as_str().unwrap_or("—").to_string(),
                start.map(fmt_local).unwrap_or_else(|| "—".to_string()),
                start.map(time_until).unwrap_or_default(),
                fmt_el(p["max_el"].as_f64().unwrap_or(0.0)),
                duration,
            ]
        }).collect();
        print_table(w, &["Satellite", "Start (local)", "Until", "Max El", "Duration"], &rows);
    }

    let _ = writeln!(w);
    Ok(())
}

// ── watch loop ────────────────────────────────────────────────────────────────

fn watch_loop<F>(interval: u64, mut render: F) -> anyhow::Result<()>
where
    F: FnMut(&mut Vec<u8>) -> anyhow::Result<()>,
{
    let mut started = false;
    loop {
        let mut buf: Vec<u8> = Vec::new();
        let ts = dim(&Local::now().format("%H:%M:%S  Ctrl-C to exit").to_string());
        let _ = writeln!(buf, "  {}  {}", bold("sdr --watch"), ts);
        if let Err(e) = render(&mut buf) {
            let _ = writeln!(buf, "\n  {}", red(&format!("Error: {}", e)));
        }

        if is_tty() {
            if started {
                // Restore to saved cursor position, then erase to end of screen
                print!("\x1b[u\x1b[J");
            } else {
                // Save cursor position before first print
                print!("\x1b[s");
            }
            std::io::stdout().flush().ok();
        }

        let text = String::from_utf8_lossy(&buf);
        print!("{}", text);
        std::io::stdout().flush().ok();
        started = true;

        std::thread::sleep(std::time::Duration::from_secs(interval));
    }
}

// ── main ──────────────────────────────────────────────────────────────────────

fn main() {
    // Ignore SIGPIPE so a closed terminal doesn't kill the watch loop
    unsafe { libc::signal(libc::SIGPIPE, libc::SIG_IGN); }

    let cli = Cli::parse();
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .expect("failed to build HTTP client");

    let mut so = std::io::stdout();
    let result = if cli.watch {
        let (client2, base2, count2, json2) = (&client, cli.url.clone(), cli.count, cli.json);
        let cmd = cli.command;
        watch_loop(cli.interval, move |buf| match &cmd {
            None => cmd_dashboard(buf, client2, &base2, count2),
            Some(Command::Status) => cmd_status(buf, client2, &base2, json2),
            Some(Command::Rules) => cmd_rules(buf, client2, &base2, json2),
            Some(Command::Overhead { min_el }) => cmd_overhead(buf, client2, &base2, *min_el, json2),
            _ => {
                let _ = writeln!(buf, "{}", yellow("  --watch not supported for this subcommand"));
                Ok(())
            }
        })
    } else {
        match &cli.command {
            None => cmd_dashboard(&mut so, &client, &cli.url, cli.count),
            Some(Command::Status) => cmd_status(&mut so, &client, &cli.url, cli.json),
            Some(Command::Overhead { min_el }) => cmd_overhead(&mut so, &client, &cli.url, *min_el, cli.json),
            Some(Command::Passes { norad, hours, min_el }) => cmd_passes(&client, &cli.url, *norad, *hours, *min_el, cli.json),
            Some(Command::Rules) => cmd_rules(&mut so, &client, &cli.url, cli.json),
            Some(Command::Rule { action, id }) => cmd_rule_toggle(&client, &cli.url, id, matches!(action, RuleAction::Enable)),
            Some(Command::Captures { norad, limit }) => cmd_captures(&client, &cli.url, *norad, *limit, cli.json),
            Some(Command::Scan { norad, duration }) => cmd_scan(&client, &cli.url, *norad, *duration),
            Some(Command::Report { capture_id }) => cmd_report(&client, &cli.url, capture_id),
            Some(Command::Logs { tail }) => cmd_logs(&client, &cli.url, *tail),
        }
    };

    if let Err(e) = result {
        let msg = e.to_string();
        if msg.contains("Connection refused") || msg.contains("os error") {
            eprintln!("{}", red(&format!("\n  Cannot reach {}: {}", cli.url, msg)));
            eprintln!("{}\n", dim("  Is the service running? systemctl --user status satellites-overhead.service"));
        } else {
            eprintln!("{}\n", red(&format!("\n  Error: {}", msg)));
        }
        std::process::exit(1);
    }
}
