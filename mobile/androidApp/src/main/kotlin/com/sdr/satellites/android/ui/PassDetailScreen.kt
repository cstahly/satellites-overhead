package com.sdr.satellites.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sdr.satellites.android.viewmodel.PassesViewModel
import com.sdr.satellites.model.Pass

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PassDetailScreen(
    onBack: () -> Unit,
    vm: PassesViewModel = viewModel(),
) {
    val pass by vm.selectedPass.collectAsState()
    val scanResult by vm.scanResult.collectAsState()
    var showScanDialog by remember { mutableStateOf(false) }
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(scanResult) {
        scanResult?.let {
            snackbar.showSnackbar(it)
            vm.clearScanResult()
        }
    }

    val p = pass ?: run { onBack(); return }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(p.name, fontWeight = FontWeight.SemiBold) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
            )
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { innerPadding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(innerPadding),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            contentPadding = PaddingValues(16.dp),
        ) {
            item {
                Text("Sky Track", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            item {
                PassSkyPlot(
                    pass = p,
                    modifier = Modifier.fillMaxWidth().aspectRatio(1f),
                )
            }
            item {
                SdrCard {
                    LabelValue("AOS", isoTime(p.aos))
                    LabelValue("LOS", isoTime(p.los))
                    LabelValue("Duration", formatDuration(p.durationSeconds))
                    LabelValue("Peak elevation", "%.1f°".format(p.maxElevation))
                    LabelValue("Azimuth", "${p.aosAzimuth.toInt()}° → ${p.maxAzimuth.toInt()}° → ${p.losAzimuth.toInt()}°")
                    LabelValue("NORAD", "${p.norad}")
                }
            }
            item {
                Button(
                    onClick = { showScanDialog = true },
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(containerColor = SdrGreen, contentColor = Color(0xFF07120D)),
                ) {
                    Text("Queue Capture", fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }

    if (showScanDialog) {
        AlertDialog(
            onDismissRequest = { showScanDialog = false },
            title = { Text("Scan ${p.name}?") },
            text = { Text("Queue a ${p.durationSeconds / 60}m ${p.durationSeconds % 60}s capture.") },
            confirmButton = {
                TextButton(onClick = { vm.triggerScan(p); showScanDialog = false }) { Text("Queue") }
            },
            dismissButton = {
                TextButton(onClick = { showScanDialog = false }) { Text("Cancel") }
            },
        )
    }
}

@Composable
fun PassSkyPlot(pass: Pass, modifier: Modifier = Modifier) {
    SkyPlotCanvas(
        modifier = modifier,
        trackPoints = pass.track,
    )
}
