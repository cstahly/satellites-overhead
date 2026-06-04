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

    init { load() }

    fun load(norad: Int? = null, hours: Int = 24) {
        viewModelScope.launch {
            _loading.value = true
            val lat = settings.getString(KEY_LATITUDE, DEFAULT_LAT).toDoubleOrNull() ?: 40.42
            val lon = settings.getString(KEY_LONGITUDE, DEFAULT_LON).toDoubleOrNull() ?: -86.88
            val alt = settings.getString(KEY_ALTITUDE_M, DEFAULT_ALT).toDoubleOrNull() ?: 180.0
            runCatching { api.getPasses(norad ?: 59051, hours, 10.0, lat, lon, alt) }
                .onSuccess { _passes.value = it; _error.value = null }
                .onFailure { _error.value = it.message }
            _loading.value = false
        }
    }
}
