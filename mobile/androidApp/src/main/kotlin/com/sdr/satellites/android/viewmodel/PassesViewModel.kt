package com.sdr.satellites.android.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.sdr.satellites.android.SatellitesApp
import com.sdr.satellites.model.Pass
import com.sdr.satellites.store.DEFAULT_ALT
import com.sdr.satellites.store.DEFAULT_LAT
import com.sdr.satellites.store.DEFAULT_LON
import com.sdr.satellites.store.KEY_ALTITUDE_M
import com.sdr.satellites.store.KEY_LATITUDE
import com.sdr.satellites.store.KEY_LONGITUDE
import com.sdr.satellites.model.ScanNowRequest
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class PassesViewModel(application: Application) : AndroidViewModel(application) {
    private val app get() = getApplication<SatellitesApp>()
    private val api get() = app.api
    private val settings get() = app.settings

    private val _passes = MutableStateFlow<List<Pass>>(emptyList())
    val passes: StateFlow<List<Pass>> = _passes

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error

    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading

    private val _selectedPass = MutableStateFlow<com.sdr.satellites.model.Pass?>(null)
    val selectedPass: StateFlow<com.sdr.satellites.model.Pass?> = _selectedPass

    private val _scanResult = MutableStateFlow<String?>(null)
    val scanResult: StateFlow<String?> = _scanResult

    init { load() }

    fun select(pass: com.sdr.satellites.model.Pass) { _selectedPass.value = pass }

    fun triggerScan(pass: com.sdr.satellites.model.Pass) {
        viewModelScope.launch {
            runCatching {
                api.triggerScanNow(ScanNowRequest(norad = pass.norad, name = pass.name, durationSeconds = pass.durationSeconds))
            }
            .onSuccess { _scanResult.value = "Queued ${pass.name} (${pass.durationSeconds / 60}m ${pass.durationSeconds % 60}s)" }
            .onFailure { _scanResult.value = "Error: ${it.message}" }
        }
    }

    fun clearScanResult() { _scanResult.value = null }

    fun load(hours: Int = 24) {
        viewModelScope.launch {
            _loading.value = true
            val lat = settings.getString(KEY_LATITUDE, DEFAULT_LAT).toDoubleOrNull() ?: 40.42
            val lon = settings.getString(KEY_LONGITUDE, DEFAULT_LON).toDoubleOrNull() ?: -86.88
            val alt = settings.getString(KEY_ALTITUDE_M, DEFAULT_ALT).toDoubleOrNull() ?: 180.0
            runCatching {
                val norads = api.getRules().map { it.norad }.distinct()
                if (norads.isEmpty()) return@runCatching emptyList<Pass>()
                coroutineScope {
                    norads.map { norad ->
                        async { runCatching { api.getPasses(norad, hours, 10.0, lat, lon, alt) }.getOrDefault(emptyList()) }
                    }.awaitAll().flatten().sortedBy { it.aos }.take(20)
                }
            }
                .onSuccess { _passes.value = it; _error.value = null }
                .onFailure { _error.value = it.message }
            _loading.value = false
        }
    }
}
