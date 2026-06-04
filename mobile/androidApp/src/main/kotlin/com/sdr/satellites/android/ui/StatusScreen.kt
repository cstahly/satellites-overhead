package com.sdr.satellites.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Circle
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sdr.satellites.android.viewmodel.StatusViewModel
import com.sdr.satellites.model.SchedulerStatus

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StatusScreen(vm: StatusViewModel = viewModel()) {
    val status by vm.status.collectAsState()
    val error by vm.error.collectAsState()
    val loading by vm.loading.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Scheduler Status") },
                actions = {
                    IconButton(onClick = { vm.refresh() }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState()),
        ) {
            if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())

            error?.let {
                Text(
                    text = it,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(16.dp),
                )
            }

            status?.let { StatusCard(it) }
                ?: if (!loading) Text("No status — check server settings.", Modifier.padding(16.dp))
        }
    }
}

@Composable
private fun StatusCard(status: SchedulerStatus) {
    Card(Modifier.fillMaxWidth().padding(16.dp)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(
                    Icons.Default.Circle,
                    contentDescription = null,
                    tint = if (status.live) Color(0xFF4CAF50) else Color(0xFF9E9E9E),
                    modifier = Modifier.size(12.dp),
                )
                Text(status.state.uppercase(), style = MaterialTheme.typography.titleMedium)
            }
            Text(status.message, style = MaterialTheme.typography.bodyMedium)
            LabeledValue("Queue", status.queueCount.toString())
            LabeledValue("Updated", status.updatedAt)
            LabeledValue("Age", "${status.statusAgeSeconds.toInt()}s")

            status.currentJob?.let { job ->
                Text("Current Job", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 8.dp))
                LabeledValue("Label", job.label)
                job.fireTime?.let { LabeledValue("Fire time", it) }
                job.frequencyHz?.let { LabeledValue("Frequency", "${(it / 1e6).format(3)} MHz") }
                job.durationSeconds?.let { LabeledValue("Duration", "${it}s") }
                job.lnaGain?.let { LabeledValue("Gains", "LNA=$it VGA=${job.vgaGain} AMP=${job.amp}") }
            }
        }
    }
}

@Composable
private fun LabeledValue(label: String, value: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodyMedium)
    }
}

private fun Double.format(decimals: Int) = "%.${decimals}f".format(this)
