package com.sdr.satellites.android

import android.app.Application
import com.sdr.satellites.api.SatellitesApi
import com.sdr.satellites.store.DEFAULT_SERVER_URL
import com.sdr.satellites.store.KEY_BEARER_TOKEN
import com.sdr.satellites.store.KEY_SERVER_URL
import com.sdr.satellites.store.PlatformSettings

class SatellitesApp : Application() {
    lateinit var settings: PlatformSettings
    lateinit var api: SatellitesApi

    override fun onCreate() {
        super.onCreate()
        settings = PlatformSettings(this)
        api = buildApi()
    }

    fun rebuildApi() {
        api.close()
        api = buildApi()
    }

    private fun buildApi(): SatellitesApi {
        val url = settings.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL)
        val token = settings.getString(KEY_BEARER_TOKEN)
        return SatellitesApi(url, token)
    }
}
