package com.sdr.satellites.android.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.sdr.satellites.android.SatellitesApp
import com.sdr.satellites.model.SchedulerStatus
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class StatusViewModel(application: Application) : AndroidViewModel(application) {
    private val api get() = (getApplication<SatellitesApp>()).api

    private val _status = MutableStateFlow<SchedulerStatus?>(null)
    val status: StateFlow<SchedulerStatus?> = _status

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error

    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading

    init { startPolling() }

    private fun startPolling() {
        viewModelScope.launch {
            while (true) {
                refresh()
                delay(10_000)
            }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            _loading.value = true
            runCatching { api.getStatus() }
                .onSuccess { _status.value = it; _error.value = null }
                .onFailure { _error.value = it.message }
            _loading.value = false
        }
    }
}
