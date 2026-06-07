package com.sdr.satellites.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sdr.satellites.android.viewmodel.RulesViewModel
import com.sdr.satellites.model.Rule

@Composable
fun RulesScreen(vm: RulesViewModel = viewModel()) {
    val rules by vm.rules.collectAsState()
    val error by vm.error.collectAsState()
    val loading by vm.loading.collectAsState()

    SdrScaffold(
        title = "Rules",
        subtitle = "Recurring scheduler targets",
        loading = loading,
        error = error,
        onRefresh = { vm.load() },
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(10.dp),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 14.dp),
        ) {
            if (rules.isEmpty() && !loading) {
                item { EmptyMessage("No scheduler rules configured.") }
            }
            items(rules, key = { it.id }) { rule ->
                RuleCard(rule = rule, onEnabled = { vm.setEnabled(rule, it) })
            }
        }
    }
}

@Composable
private fun RuleCard(rule: Rule, onEnabled: (Boolean) -> Unit) {
    SdrCard {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                Text(rule.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text("NORAD ${rule.norad}  |  ${rule.profile ?: "profile"}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Switch(checked = rule.enabled, onCheckedChange = onEnabled)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            rule.frequencyHz?.let { OutlinePill("%.3f MHz".format(it / 1e6), SdrBlue) }
            rule.minPeakElevation?.let { OutlinePill("min %.0f deg".format(it), elevationColor(it)) }
            rule.priority?.takeIf { it != 0.0 }?.let { OutlinePill("prio %.0f".format(it), SdrYellow) }
        }
        LabelValue("Gains", "LNA=${rule.lnaGain ?: "--"} VGA=${rule.vgaGain ?: "--"} AMP=${rule.amp ?: "--"}")
        LabelValue("Window", "${rule.startOffsetSeconds ?: -30}s / +${rule.endOffsetSeconds ?: 60}s")
    }
}
