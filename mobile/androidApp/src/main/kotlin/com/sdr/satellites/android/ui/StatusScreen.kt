package com.sdr.satellites.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Circle
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sdr.satellites.android.viewmodel.StatusViewModel
import com.sdr.satellites.model.CurrentJob
import com.sdr.satellites.model.SchedulerStatus

@Composable
fun StatusScreen(vm: StatusViewModel = viewModel()) {
    val status by vm.status.collectAsState()
    val error by vm.error.collectAsState()
    val loading by vm.loading.collectAsState()

    SdrScaffold(
        title = "Satellites Overhead",
        subtitle = "SDR scheduler dashboard",
        loading = loading,
        error = error,
        onRefresh = { vm.refresh() },
    ) {
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(ScreenPadding),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            val current = status
            if (current == null && !loading) {
                EmptyMessage("No scheduler status yet. Check server URL and token.")
            } else if (current != null) {
                HeroStatus(current)
                CurrentJobCard(current.currentJob)
                SdrCard {
                    Text("System", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    LabelValue("Message", current.message)
                    LabelValue("Updated", isoDateTime(current.updatedAt))
                    LabelValue("Age", "${current.statusAgeSeconds.toInt()}s")
                    LabelValue("PID", current.pid.toString())
                }
            }
        }
    }
}

@Composable
private fun HeroStatus(status: SchedulerStatus) {
    SdrCard {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.Top) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        Icons.Default.Circle,
                        contentDescription = null,
                        tint = if (status.live) SdrGreen else MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 1.dp),
                    )
                    Text(status.state.uppercase(), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                }
                Text(
                    if (status.live) "Capture running" else "Next capture pending",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Pill(if (status.fresh) "fresh" else "stale", if (status.fresh) SdrGreen else SdrRed)
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Metric("Queue", status.queueCount.toString(), Modifier.weight(1f))
            Metric("Live", if (status.live) "yes" else "no", Modifier.weight(1f))
            Metric("Age", "${status.statusAgeSeconds.toInt()}s", Modifier.weight(1f))
        }
    }
}

@Composable
private fun CurrentJobCard(job: CurrentJob?) {
    SdrCard {
        Text("Current Job", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        if (job == null) {
            Text("Idle. Waiting for the next scheduler window.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            return@SdrCard
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinePill(job.type, SdrBlue)
            if (job.partial) OutlinePill("partial", SdrYellow)
        }
        LabelValue("Label", job.label)
        job.fireTime?.let { LabelValue("Fire", isoDateTime(it)) }
        job.queuedAt?.let { LabelValue("Queued", isoDateTime(it)) }
        job.frequencyHz?.let { LabelValue("Frequency", "%.3f MHz".format(it / 1e6)) }
        job.durationSeconds?.let { LabelValue("Duration", formatDuration(it)) }
        LabelValue("Gains", "LNA=${job.lnaGain ?: "--"} VGA=${job.vgaGain ?: "--"} AMP=${job.amp ?: "--"}")
    }
}
