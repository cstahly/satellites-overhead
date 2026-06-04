package com.sdr.satellites.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sdr.satellites.android.viewmodel.CapturesViewModel
import com.sdr.satellites.model.Capture

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CapturesScreen(vm: CapturesViewModel = viewModel()) {
    val captures by vm.captures.collectAsState()
    val error by vm.error.collectAsState()
    val loading by vm.loading.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Capture History") },
                actions = {
                    IconButton(onClick = { vm.load() }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            error?.let { Text(it, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(16.dp)) }

            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp)) {
                if (captures.isEmpty() && !loading) {
                    item { Text("No captures found.") }
                }
                items(captures) { capture -> CaptureCard(capture) }
            }
        }
    }
}

@Composable
private fun CaptureCard(capture: Capture) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(capture.name, style = MaterialTheme.typography.titleSmall)
                capture.sizeBytes?.let {
                    Text(formatBytes(it), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            capture.startedAt?.let { Text(it.substringBefore("T") + " " + it.substringAfter("T").substringBefore("Z") + " UTC", style = MaterialTheme.typography.bodySmall) }
            capture.profile?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            capture.frequencyHz?.let { Text("${(it / 1e6).let { f -> "%.3f".format(f) }} MHz  •  LNA=${capture.lnaGain} VGA=${capture.vgaGain}", style = MaterialTheme.typography.bodySmall) }
        }
    }
}

private fun formatBytes(bytes: Long): String = when {
    bytes >= 1_000_000_000 -> "%.1f GB".format(bytes / 1e9)
    bytes >= 1_000_000 -> "%.1f MB".format(bytes / 1e6)
    bytes >= 1_000 -> "%.1f KB".format(bytes / 1e3)
    else -> "$bytes B"
}
