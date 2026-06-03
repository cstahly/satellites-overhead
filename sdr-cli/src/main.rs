use chrono::{DateTime, Duration, Local, Utc};
use clap::{Parser, Subcommand};
use serde_json::Value;
use std::io::IsTerminal;

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

fn print_table(headers: &[&str], rows: &[Vec<String>]) {
    if rows.is_empty() {
        println!("{}", dim("  (no results)"));
        return;
    }
    let w = col_widths(headers, rows);
    let header_row: Vec<String> = headers.iter().enumerate()
        .map(|(i, h)| format!("{:<width$}", h, width = w[i]))
        .collect();
    println!("  {}", bold(&header_row.join("  ")));
    let sep: Vec<String> = w.iter().map(|&n| "-".repeat(n)).collect();
    println!("{}", dim(&format!("  {}", sep.join("  "))));
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
            let pad = if i < w.len() && w[i] > visible_len { w[i] - visible_len } else { 0 };
            format!("{}{}", cell, " ".repeat(pad))
        }).collect();
        println!("  {}", cells.join("  "));
    }
}

// ── HTTP ──────────────────────────────────────────────────────────────────────

fn get(client: &reqwest::blocking::Client, url: &str) -> anyhow::Result<Value> {
    Ok(client.get(url).send()?.json()?)
}

fn get_text(client: &reqwest::blocking::Client, url: &str) -> anyhow::Result<String> {
    Ok(client.get(url).send()?.text()?)
}

fn post(client: &reqwest::blocking::Client, url: &str, body: &Value) -> anyhow::Result<Value> {
    Ok(client.post(url).json(body).send()?.json()?)
}

fn delete_req(client: &reqwest::blocking::Client, url: &str) -> anyhow::Result<Value> {
    Ok(client.delete(url).send()?.json()?)
}

// ── CLI definition ────────────────────────────────────────────────────────────

#[derive(Parser)]
#[command(name = "sdr", about = "Satellite SDR scheduler CLI", version)]
struct Cli {
    #[arg(long, default_value = DEFAULT_URL, global = true)]
    url: String,
    #[arg(long, global = true, help = "Raw JSON output")]
    json: bool,
    #[command(subcommand)]
    command: Command,
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
}

#[derive(Clone, clap::ValueEnum)]
enum RuleAction { Enable, Disable }

// ── command handlers ──────────────────────────────────────────────────────────

fn cmd_status(client: &reqwest::blocking::Client, base: &str, as_json: bool) -> anyhow::Result<()> {
    let data = get(client, &format!("{}/scheduler/status", base))?;
    if as_json { println!("{}", serde_json::to_string_pretty(&data)?); return Ok(()); }

    let state = data["state"].as_str().unwrap_or("unknown");
    let live = data["live"].as_bool().unwrap_or(false);
    let state_str = if live { green("running") } else if state == "idle" { yellow("idle") } else { red(state) };
    let age = data["status_age_s"].as_f64();
    let age_str = age.map(|a| dim(&format!("  updated {}s ago", a as u64))).unwrap_or_default();

    println!("\n  Scheduler  {}{}", state_str, age_str);
    println!("  Queue      {} command(s) pending", data["queue_count"].as_u64().unwrap_or(0));

    if let Some(job) = data["current_job"].as_object() {
        let label = job.get("label").and_then(|v| v.as_str()).unwrap_or("—");
        let msg = data["message"].as_str().unwrap_or("");
        if live {
            let freq = job.get("frequency_hz").and_then(|v| v.as_f64());
            let freq_str = freq.map(|f| format!("  {:.3} MHz", f / 1e6)).unwrap_or_default();
            let out = job.get("output").and_then(|v| v.as_str()).unwrap_or("");
            println!("  Job        {}{}", bold(label), freq_str);
            if !out.is_empty() { println!("  Output     {}", dim(out)); }
        } else {
            let fire = job.get("fire_time").and_then(|v| v.as_str()).unwrap_or("");
            let local = if fire.is_empty() { "—".to_string() } else { fmt_local(fire) };
            let until = if fire.is_empty() { String::new() } else { time_until(fire) };
            println!("  Next       {}  {}  {}", bold(label), local, until);
        }
        if !msg.is_empty() { println!("  Status     {}", dim(msg)); }
    }
    println!();
    Ok(())
}

fn cmd_overhead(client: &reqwest::blocking::Client, base: &str, min_el: f64, as_json: bool) -> anyhow::Result<()> {
    let start = (Utc::now() - Duration::hours(2)).format("%Y-%m-%dT%H:%M:%SZ").to_string();
    let url = format!("{}/passes?lat=40.42&lon=-86.88&alt_m=180&hours=2.5&min_el={}&group=radio&track_step_s=60&start={}", base, min_el, start);
    let data = get(client, &url)?;
    if as_json { println!("{}", serde_json::to_string_pretty(&data)?); return Ok(()); }

    let now_ts = Utc::now().timestamp() as f64;
    let passes = data.as_array().map(|a| a.as_slice()).unwrap_or(&[]);
    let overhead: Vec<&Value> = passes.iter().filter(|p| {
        let aos = p["aos"].as_str().and_then(|s| parse_dt(s)).map(|d| d.timestamp() as f64).unwrap_or(f64::MAX);
        let los = p["los"].as_str().and_then(|s| parse_dt(s)).map(|d| d.timestamp() as f64).unwrap_or(0.0);
        aos <= now_ts && now_ts <= los
    }).collect();

    if overhead.is_empty() {
        println!("{}", dim("  Nothing above the horizon right now."));
        return Ok(());
    }
    println!();
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
    print_table(&["Satellite", "NORAD", "Max El", ""], &rows);
    println!();
    Ok(())
}

fn cmd_passes(client: &reqwest::blocking::Client, base: &str, norad: Option<u32>, hours: f64, min_el: f64, as_json: bool) -> anyhow::Result<()> {
    let mut url = format!("{}/passes?lat=40.42&lon=-86.88&alt_m=180&hours={}&min_el={}&group=radio&track_step_s=60", base, hours, min_el);
    if let Some(n) = norad { url.push_str(&format!("&norad={}", n)); }
    let data = get(client, &url)?;
    if as_json { println!("{}", serde_json::to_string_pretty(&data)?); return Ok(()); }

    let passes = data.as_array().map(|a| a.as_slice()).unwrap_or(&[]);
    if passes.is_empty() { println!("{}", dim("  No passes found.")); return Ok(()); }
    println!();
    let rows: Vec<Vec<String>> = passes.iter().map(|p| vec![
        p["name"].as_str().unwrap_or("—").to_string(),
        p["norad"].to_string(),
        p["aos"].as_str().map(fmt_local).unwrap_or_else(|| "—".to_string()),
        p["aos"].as_str().map(time_until).unwrap_or_default(),
        fmt_el(p["max_el"].as_f64().unwrap_or(0.0)),
        fmt_dur(p["duration_s"].as_f64().unwrap_or(0.0)),
    ]).collect();
    print_table(&["Satellite", "NORAD", "AOS (local)", "Until", "Max El", "Duration"], &rows);
    println!();
    Ok(())
}

fn cmd_rules(client: &reqwest::blocking::Client, base: &str, as_json: bool) -> anyhow::Result<()> {
    let data = get(client, &format!("{}/scheduler/rules", base))?;
    if as_json { println!("{}", serde_json::to_string_pretty(&data)?); return Ok(()); }

    let rules = data.as_array().map(|a| a.as_slice()).unwrap_or(&[]);
    if rules.is_empty() { println!("{}", dim("  No rules configured.")); return Ok(()); }
    println!();
    let rows: Vec<Vec<String>> = rules.iter().map(|r| {
        let enabled = if r["enabled"].as_bool().unwrap_or(false) { green("yes") } else { red("no") };
        let freq = r["frequency_hz"].as_f64().map(|f| format!("{:.3}", f / 1e6)).unwrap_or_else(|| "—".to_string());
        vec![
            r["id"].as_str().unwrap_or("—").to_string(),
            r["name"].as_str().unwrap_or("—").to_string(),
            enabled,
            freq,
            r["profile"].as_str().unwrap_or("—").to_string(),
            format!("{} / {} / {}", r["lna_gain"], r["vga_gain"], r["amp"]),
            format!("{}°", r["min_peak_el"].as_f64().unwrap_or(0.0)),
        ]
    }).collect();
    print_table(&["ID", "Satellite", "On", "MHz", "Profile", "LNA/VGA/Amp", "Min El"], &rows);
    println!();
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
    print_table(&["Time", "Satellite", "Profile", "Duration", "Size", "CADU", "Report", "ID"], &rows);
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

fn cmd_report(client: &reqwest::blocking::Client, base: &str, capture_id: &str) -> anyhow::Result<()> {
    let text = get_text(client, &format!("{}/captures/{}/report", base, capture_id))?;
    println!("{}", text);
    Ok(())
}

// ── main ──────────────────────────────────────────────────────────────────────

fn main() {
    let cli = Cli::parse();
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .expect("failed to build HTTP client");

    let result = match &cli.command {
        Command::Status => cmd_status(&client, &cli.url, cli.json),
        Command::Overhead { min_el } => cmd_overhead(&client, &cli.url, *min_el, cli.json),
        Command::Passes { norad, hours, min_el } => cmd_passes(&client, &cli.url, *norad, *hours, *min_el, cli.json),
        Command::Rules => cmd_rules(&client, &cli.url, cli.json),
        Command::Rule { action, id } => cmd_rule_toggle(&client, &cli.url, id, matches!(action, RuleAction::Enable)),
        Command::Captures { norad, limit } => cmd_captures(&client, &cli.url, *norad, *limit, cli.json),
        Command::Scan { norad, duration } => cmd_scan(&client, &cli.url, *norad, *duration),
        Command::Report { capture_id } => cmd_report(&client, &cli.url, capture_id),
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
