package com.sdr.satellites.android.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.sdr.satellites.android.SatellitesApp
import com.sdr.satellites.model.SdrEvent
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class EventsViewModel(application: Application) : AndroidViewModel(application) {
    private val api get() = (getApplication<SatellitesApp>()).api

    private val _events = MutableStateFlow<List<SdrEvent>>(emptyList())
    val events: StateFlow<List<SdrEvent>> = _events

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error

    private var latestId: String? = null

    init { startPolling() }

    private fun startPolling() {
        viewModelScope.launch {
            while (true) {
                refresh()
                delay(15_000)
            }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            runCatching { api.getEvents(limit = 50) }
                .onSuccess { incoming ->
                    if (incoming.isNotEmpty()) {
                        val merged = (incoming + _events.value)
                            .distinctBy { it.id }
                            .take(100)
                        _events.value = merged
                        latestId = merged.first().id
                    }
                    _error.value = null
                }
                .onFailure { _error.value = it.message }
        }
    }
}
