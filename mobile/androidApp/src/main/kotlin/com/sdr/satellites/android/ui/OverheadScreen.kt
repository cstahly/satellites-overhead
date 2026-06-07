package com.sdr.satellites.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sdr.satellites.android.viewmodel.OverheadViewModel
import com.sdr.satellites.model.OverheadSat

@Composable
fun OverheadScreen(vm: OverheadViewModel = viewModel()) {
    val sats by vm.sats.collectAsState()
    val error by vm.error.collectAsState()
    val loading by vm.loading.collectAsState()
    var selectedNorad by remember { mutableStateOf<Int?>(null) }

    LaunchedEffect(Unit) { vm.load() }

    SdrScaffold(
        title = "Overhead",
        subtitle = "Satellites currently above horizon",
        loading = loading,
        error = error,
        onRefresh = { vm.load() },
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 14.dp),
        ) {
            if (sats.isNotEmpty()) {
                item {
                    SkyPlotCanvas(
                        modifier = Modifier.fillMaxWidth().aspectRatio(1f),
                        overheadSats = sats,
                        selectedNorad = selectedNorad,
                    )
                }
            }
            if (sats.isEmpty() && !loading) {
                item { EmptyMessage("No satellites above the horizon right now.") }
            }
            items(sats, key = { it.norad }) { sat ->
                OverheadSatCard(sat, selected = selectedNorad == sat.norad) {
                    selectedNorad = if (selectedNorad == sat.norad) null else sat.norad
                }
            }
        }
    }
}

@Composable
private fun OverheadSatCard(sat: OverheadSat, selected: Boolean, onClick: () -> Unit) {
    SdrCard(
        modifier = androidx.compose.ui.Modifier
            .fillMaxWidth()
            .let { if (selected) it else it },
    ) {
        androidx.compose.foundation.layout.Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            androidx.compose.foundation.layout.Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(sat.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text("NORAD ${sat.norad}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Pill("%.0f°".format(sat.el), elevationColor(sat.el))
        }
        androidx.compose.foundation.layout.Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinePill("Az %.0f°".format(sat.az), SdrBlue)
            OutlinePill("%.0f km".format(sat.rangeKm), MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
