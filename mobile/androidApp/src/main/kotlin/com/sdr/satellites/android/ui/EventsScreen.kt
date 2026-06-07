package com.sdr.satellites.android.ui

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
import com.sdr.satellites.android.viewmodel.EventsViewModel
import com.sdr.satellites.model.SdrEvent

@Composable
fun EventsScreen(vm: EventsViewModel = viewModel()) {
    val events by vm.events.collectAsState()
    val error by vm.error.collectAsState()

    SdrScaffold(
        title = "Diagnostics",
        subtitle = "Scheduler event stream",
        error = error,
        onRefresh = { vm.refresh() },
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(10.dp),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 14.dp),
        ) {
            if (events.isEmpty()) {
                item { EmptyMessage("No events yet.") }
            }
            items(events, key = { it.id }) { event -> EventRow(event) }
        }
    }
}

@Composable
private fun EventRow(event: SdrEvent) {
    SdrCard {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(event.type, style = MaterialTheme.typography.titleSmall, color = eventTypeColor(event.type), fontWeight = FontWeight.SemiBold)
            Text(isoTime(event.timestamp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        event.source?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
    }
}

@Composable
private fun eventTypeColor(type: String) = when {
    type.startsWith("capture.") -> SdrBlue
    type.startsWith("scheduler.") -> SdrGreen
    type.startsWith("monitor.") -> SdrYellow
    else -> MaterialTheme.colorScheme.onSurface
}
