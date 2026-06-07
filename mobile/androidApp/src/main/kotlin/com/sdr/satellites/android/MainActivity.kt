package com.sdr.satellites.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.graphics.Color
import com.sdr.satellites.android.ui.AppNavigation

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(
                colorScheme = darkColorScheme(
                    primary = Color(0xFF39D98A),
                    secondary = Color(0xFF58A6FF),
                    tertiary = Color(0xFFFFC857),
                    background = Color(0xFF070B12),
                    surface = Color(0xFF111827),
                    surfaceVariant = Color(0xFF1F2937),
                    onBackground = Color(0xFFE6EDF3),
                    onSurface = Color(0xFFE6EDF3),
                    onSurfaceVariant = Color(0xFF9CA3AF),
                ),
            ) {
                AppNavigation()
            }
        }
    }
}
