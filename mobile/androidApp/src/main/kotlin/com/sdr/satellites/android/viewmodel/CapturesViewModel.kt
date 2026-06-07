package com.sdr.satellites.android.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.sdr.satellites.android.SatellitesApp
import com.sdr.satellites.model.Capture
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class CapturesViewModel(application: Application) : AndroidViewModel(application) {
    private val api get() = (getApplication<SatellitesApp>()).api

    private val _captures = MutableStateFlow<List<Capture>>(emptyList())
    val captures: StateFlow<List<Capture>> = _captures

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error

    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading

    private val _selectedCapture = MutableStateFlow<Capture?>(null)
    val selectedCapture: StateFlow<Capture?> = _selectedCapture

    private val _report = MutableStateFlow<String?>(null)
    val report: StateFlow<String?> = _report

    private val _reportError = MutableStateFlow<String?>(null)
    val reportError: StateFlow<String?> = _reportError

    private val _loadingReport = MutableStateFlow(false)
    val loadingReport: StateFlow<Boolean> = _loadingReport

    init { load() }

    fun load(norad: Int? = null) {
        viewModelScope.launch {
            _loading.value = true
            runCatching { api.getCaptures(norad ?: -1) }
                .onSuccess { _captures.value = it; _error.value = null }
                .onFailure { _error.value = it.message }
            _loading.value = false
        }
    }

    fun select(capture: Capture) {
        _selectedCapture.value = capture
        _report.value = null
        _reportError.value = null
    }

    fun loadReport() {
        val id = _selectedCapture.value?.id ?: return
        viewModelScope.launch {
            _loadingReport.value = true
            runCatching { api.getCaptureReport(id) }
                .onSuccess { _report.value = it; _reportError.value = null }
                .onFailure { _reportError.value = it.message }
            _loadingReport.value = false
        }
    }
}
