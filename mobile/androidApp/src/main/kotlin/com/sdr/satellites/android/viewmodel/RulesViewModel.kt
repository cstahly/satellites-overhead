package com.sdr.satellites.android.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.sdr.satellites.android.SatellitesApp
import com.sdr.satellites.model.Rule
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class RulesViewModel(application: Application) : AndroidViewModel(application) {
    private val api get() = getApplication<SatellitesApp>().api

    private val _rules = MutableStateFlow<List<Rule>>(emptyList())
    val rules: StateFlow<List<Rule>> = _rules

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error

    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading

    init { load() }

    fun load() {
        viewModelScope.launch {
            _loading.value = true
            runCatching { api.getRules() }
                .onSuccess { _rules.value = it; _error.value = null }
                .onFailure { _error.value = it.message }
            _loading.value = false
        }
    }

    fun setEnabled(rule: Rule, enabled: Boolean) {
        viewModelScope.launch {
            runCatching { api.setRuleEnabled(rule.id, enabled) }
                .onSuccess { load() }
                .onFailure { _error.value = it.message }
        }
    }
}
