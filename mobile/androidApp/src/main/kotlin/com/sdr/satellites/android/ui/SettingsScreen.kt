package com.sdr.satellites.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.sdr.satellites.android.SatellitesApp
import com.sdr.satellites.store.DEFAULT_ALT
import com.sdr.satellites.store.DEFAULT_LAT
import com.sdr.satellites.store.DEFAULT_LON
import com.sdr.satellites.store.DEFAULT_SERVER_URL
import com.sdr.satellites.store.KEY_ALTITUDE_M
import com.sdr.satellites.store.KEY_BEARER_TOKEN
import com.sdr.satellites.store.KEY_LATITUDE
import com.sdr.satellites.store.KEY_LONGITUDE
import com.sdr.satellites.store.KEY_SERVER_URL

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(onSaved: () -> Unit) {
    val app = LocalContext.current.applicationContext as SatellitesApp
    val settings = app.settings

    var serverUrl by remember { mutableStateOf(settings.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL)) }
    var token by remember { mutableStateOf(settings.getString(KEY_BEARER_TOKEN)) }
    var lat by remember { mutableStateOf(settings.getString(KEY_LATITUDE, DEFAULT_LAT)) }
    var lon by remember { mutableStateOf(settings.getString(KEY_LONGITUDE, DEFAULT_LON)) }
    var alt by remember { mutableStateOf(settings.getString(KEY_ALTITUDE_M, DEFAULT_ALT)) }

    Scaffold(
        topBar = { TopAppBar(title = { Text("Settings") }) },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            OutlinedTextField(
                value = serverUrl,
                onValueChange = { serverUrl = it },
                label = { Text("Server URL") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            OutlinedTextField(
                value = token,
                onValueChange = { token = it },
                label = { Text("Bearer Token") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            )
            OutlinedTextField(
                value = lat,
                onValueChange = { lat = it },
                label = { Text("Latitude") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            )
            OutlinedTextField(
                value = lon,
                onValueChange = { lon = it },
                label = { Text("Longitude") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            )
            OutlinedTextField(
                value = alt,
                onValueChange = { alt = it },
                label = { Text("Altitude (m)") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            )
            Button(
                onClick = {
                    settings.putString(KEY_SERVER_URL, serverUrl.trimEnd('/'))
                    settings.putString(KEY_BEARER_TOKEN, token.trim())
                    settings.putString(KEY_LATITUDE, lat)
                    settings.putString(KEY_LONGITUDE, lon)
                    settings.putString(KEY_ALTITUDE_M, alt)
                    app.rebuildApi()
                    onSaved()
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Save & Reconnect")
            }
        }
    }
}
