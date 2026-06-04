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
import com.sdr.satellites.android.viewmodel.PassesViewModel
import com.sdr.satellites.model.Pass

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PassesScreen(vm: PassesViewModel = viewModel()) {
    val passes by vm.passes.collectAsState()
    val error by vm.error.collectAsState()
    val loading by vm.loading.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Upcoming Passes") },
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
                if (passes.isEmpty() && !loading) {
                    item { Text("No passes found.") }
                }
                items(passes) { pass -> PassCard(pass) }
            }
        }
    }
}

@Composable
private fun PassCard(pass: Pass) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(pass.name, style = MaterialTheme.typography.titleSmall)
                Text("%.0f°".format(pass.maxElevation), style = MaterialTheme.typography.titleSmall, color = elevationColor(pass.maxElevation))
            }
            Text("AOS ${pass.aos.substringAfter("T").substringBefore("Z")} UTC", style = MaterialTheme.typography.bodySmall)
            Text("LOS ${pass.los.substringAfter("T").substringBefore("Z")} UTC  •  ${pass.durationSeconds / 60}m ${pass.durationSeconds % 60}s", style = MaterialTheme.typography.bodySmall)
            Text("Az ${pass.aosAzimuth.toInt()}° → ${pass.maxAzimuth.toInt()}° → ${pass.losAzimuth.toInt()}°", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun elevationColor(el: Double) = when {
    el >= 60 -> MaterialTheme.colorScheme.primary
    el >= 30 -> MaterialTheme.colorScheme.tertiary
    else -> MaterialTheme.colorScheme.onSurfaceVariant
}
