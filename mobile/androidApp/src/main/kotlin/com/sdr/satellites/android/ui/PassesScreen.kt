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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sdr.satellites.android.viewmodel.PassesViewModel
import com.sdr.satellites.model.Pass

@Composable
fun PassesScreen(
    onPassTap: (Pass) -> Unit = {},
    vm: PassesViewModel = viewModel(),
) {
    val passes by vm.passes.collectAsState()
    val error by vm.error.collectAsState()
    val loading by vm.loading.collectAsState()

    SdrScaffold(
        title = "Passes",
        subtitle = "Rule-filtered upcoming windows",
        loading = loading,
        error = error,
        onRefresh = { vm.load() },
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(10.dp),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 14.dp),
        ) {
            if (passes.isEmpty() && !loading) {
                item { EmptyMessage("No passes found for the configured satellites.") }
            }
            items(passes, key = { "${it.norad}-${it.aos}" }) { pass ->
                PassCard(pass, onClick = { onPassTap(pass) })
            }
        }
    }
}

@Composable
fun PassCard(pass: Pass, onClick: () -> Unit = {}) {
    SdrCard(modifier = Modifier.clickable(onClick = onClick)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Pill("%.0f°".format(pass.maxElevation), elevationColor(pass.maxElevation))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(pass.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text("NORAD ${pass.norad}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinePill("AOS ${isoTime(pass.aos)}", SdrGreen)
            OutlinePill("LOS ${isoTime(pass.los)}", SdrYellow)
            OutlinePill(formatDuration(pass.durationSeconds), MaterialTheme.colorScheme.onSurfaceVariant)
        }
        LabelValue("Peak", "${isoTime(pass.maxTime)}  |  az ${pass.maxAzimuth.toInt()}°")
        LabelValue("Track", "${pass.aosAzimuth.toInt()}° → ${pass.maxAzimuth.toInt()}° → ${pass.losAzimuth.toInt()}°")
    }
}
