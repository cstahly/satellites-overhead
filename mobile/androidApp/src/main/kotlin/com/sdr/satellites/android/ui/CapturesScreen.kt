package com.sdr.satellites.android.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sdr.satellites.android.viewmodel.CapturesViewModel
import com.sdr.satellites.model.Capture

@Composable
fun CapturesScreen(
    onCaptureTap: (Capture) -> Unit = {},
    vm: CapturesViewModel = viewModel(),
) {
    val captures by vm.captures.collectAsState()
    val error by vm.error.collectAsState()
    val loading by vm.loading.collectAsState()

    SdrScaffold(
        title = "Captures",
        subtitle = "Recent SDR output",
        loading = loading,
        error = error,
        onRefresh = { vm.load() },
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(10.dp),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 14.dp),
        ) {
            if (captures.isEmpty() && !loading) {
                item { EmptyMessage("No captures recorded yet.") }
            }
            items(captures, key = { it.id }) { capture ->
                CaptureCard(capture, onClick = { onCaptureTap(capture) })
            }
        }
    }
}

@Composable
fun CaptureCard(capture: Capture, onClick: () -> Unit = {}) {
    SdrCard(modifier = Modifier.clickable(onClick = onClick)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(capture.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text("NORAD ${capture.norad}  |  ${capture.profile ?: "capture"}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            capture.success?.let { Pill(if (it) "ok" else "fail", if (it) SdrGreen else SdrRed) }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinePill(formatBytes(capture.sizeBytes), SdrBlue)
            capture.reportPath?.let { OutlinePill("report", SdrYellow) }
            capture.outputType?.let { OutlinePill(it, MaterialTheme.colorScheme.onSurfaceVariant) }
        }
        capture.startedAt?.let { LabelValue("Started", isoDateTime(it)) }
        capture.endedAt?.let { LabelValue("Ended", isoDateTime(it)) }
        capture.frequencyHz?.let { LabelValue("Frequency", "%.3f MHz".format(it / 1e6)) }
        LabelValue("Gains", "LNA=${capture.lnaGain ?: "--"} VGA=${capture.vgaGain ?: "--"} AMP=${capture.amp ?: "--"}")
        capture.error?.takeIf { it.isNotBlank() }?.let {
            Text(it, color = SdrRed, style = MaterialTheme.typography.bodySmall)
        }
    }
}
