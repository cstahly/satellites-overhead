package com.sdr.satellites.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sdr.satellites.android.viewmodel.CapturesViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CaptureDetailScreen(
    onBack: () -> Unit,
    vm: CapturesViewModel = viewModel(),
) {
    val capture by vm.selectedCapture.collectAsState()
    val report by vm.report.collectAsState()
    val reportError by vm.reportError.collectAsState()
    val loadingReport by vm.loadingReport.collectAsState()

    val c = capture ?: run { onBack(); return }

    LaunchedEffect(c.id) {
        if (c.reportPath != null && report == null && reportError == null) vm.loadReport()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(c.name, fontWeight = FontWeight.SemiBold) },
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
    ) { innerPadding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(innerPadding),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            contentPadding = PaddingValues(16.dp),
        ) {
            item {
                SdrCard {
                    Text("Capture", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    LabelValue("Satellite", c.name)
                    LabelValue("NORAD", "${c.norad}")
                    c.startedAt?.let { LabelValue("Started", isoDateTime(it)) }
                    c.endedAt?.let { LabelValue("Ended", isoDateTime(it)) }
                    c.profile?.let { LabelValue("Profile", it) }
                    c.frequencyHz?.let { LabelValue("Frequency", "%.3f MHz".format(it / 1e6)) }
                    c.success?.let { LabelValue("Result", if (it) "Success" else "Failed") }
                    c.error?.takeIf { it.isNotBlank() }?.let {
                        Text(it, color = SdrRed, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
            item {
                SdrCard {
                    Text("Output", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    LabelValue("Size", formatBytes(c.sizeBytes))
                    c.caduBytes?.let { LabelValue("CADU", formatBytes(it)) }
                    LabelValue("Gains", "LNA=${c.lnaGain ?: "--"} VGA=${c.vgaGain ?: "--"} AMP=${c.amp ?: "--"}")
                    c.output?.takeIf { it.isNotBlank() }?.let {
                        Text(it, style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace))
                    }
                }
            }
            item {
                SdrCard {
                    Text("Diagnostic Report", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    when {
                        loadingReport -> LinearProgressIndicator(Modifier.fillMaxWidth())
                        report != null -> Text(
                            report!!,
                            style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                        )
                        reportError != null -> Text(reportError!!, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                        c.reportPath == null -> Text("No diagnostic report for this capture.", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                        else -> Button(onClick = { vm.loadReport() }) { Text("Load Report") }
                    }
                }
            }
        }
    }
}
