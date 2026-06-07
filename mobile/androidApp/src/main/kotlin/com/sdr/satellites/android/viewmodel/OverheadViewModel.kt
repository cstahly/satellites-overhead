package com.sdr.satellites.android.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.sdr.satellites.android.SatellitesApp
import com.sdr.satellites.model.OverheadSat
import com.sdr.satellites.store.DEFAULT_ALT
import com.sdr.satellites.store.DEFAULT_LAT
import com.sdr.satellites.store.DEFAULT_LON
import com.sdr.satellites.store.KEY_ALTITUDE_M
import com.sdr.satellites.store.KEY_LATITUDE
import com.sdr.satellites.store.KEY_LONGITUDE
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class OverheadViewModel(application: Application) : AndroidViewModel(application) {
    private val app get() = getApplication<SatellitesApp>()
    private val api get() = app.api
    private val settings get() = app.settings

    private val _sats = MutableStateFlow<List<OverheadSat>>(emptyList())
    val sats: StateFlow<List<OverheadSat>> = _sats

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error

    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading

    fun load() {
        viewModelScope.launch {
            _loading.value = true
            val lat = settings.getString(KEY_LATITUDE, DEFAULT_LAT).toDoubleOrNull() ?: 40.42
            val lon = settings.getString(KEY_LONGITUDE, DEFAULT_LON).toDoubleOrNull() ?: -86.88
            val alt = settings.getString(KEY_ALTITUDE_M, DEFAULT_ALT).toDoubleOrNull() ?: 180.0
            runCatching { api.getOverhead(lat, lon, alt, 0.0) }
                .onSuccess { _sats.value = it.sortedByDescending { s -> s.el }; _error.value = null }
                .onFailure { _error.value = it.message }
            _loading.value = false
        }
    }
}
