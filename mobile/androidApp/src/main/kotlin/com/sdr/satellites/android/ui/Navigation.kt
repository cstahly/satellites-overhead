package com.sdr.satellites.android.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.Satellite
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.Stream
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController

private sealed class Screen(val route: String, val label: String) {
    object Status   : Screen("status",   "Status")
    object Passes   : Screen("passes",   "Passes")
    object Rules    : Screen("rules",    "Rules")
    object Captures : Screen("captures", "Captures")
    object Events   : Screen("events",   "Diag")
    object Overhead : Screen("overhead", "Overhead")
    object Settings : Screen("settings", "Settings")
}

private val tabScreens = listOf(
    Screen.Status,
    Screen.Passes,
    Screen.Rules,
    Screen.Captures,
    Screen.Events,
    Screen.Overhead,
    Screen.Settings,
)

@Composable
fun AppNavigation() {
    val nav = rememberNavController()
    val navBackStackEntry by nav.currentBackStackEntryAsState()
    val currentDestination = navBackStackEntry?.destination
    val isDetailRoute = currentDestination?.route?.let {
        it == "pass_detail" || it == "capture_detail"
    } == true

    Scaffold(
        bottomBar = {
            if (!isDetailRoute) {
                NavigationBar {
                    tabScreens.forEach { screen ->
                        NavigationBarItem(
                            icon = {
                                Icon(
                                    imageVector = when (screen) {
                                        Screen.Status   -> Icons.Default.Speed
                                        Screen.Passes   -> Icons.Default.Satellite
                                        Screen.Rules    -> Icons.Default.Tune
                                        Screen.Captures -> Icons.Default.History
                                        Screen.Events   -> Icons.Default.Stream
                                        Screen.Overhead -> Icons.Default.Language
                                        Screen.Settings -> Icons.Default.Settings
                                    },
                                    contentDescription = screen.label,
                                )
                            },
                            label = { Text(screen.label) },
                            selected = currentDestination?.hierarchy?.any { it.route == screen.route } == true,
                            onClick = {
                                nav.navigate(screen.route) {
                                    popUpTo(nav.graph.findStartDestination().id) { saveState = true }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                        )
                    }
                }
            }
        },
    ) { innerPadding ->
        // Shared ViewModels accessed by both list and detail screens
        val passesVm: com.sdr.satellites.android.viewmodel.PassesViewModel = viewModel()
        val capturesVm: com.sdr.satellites.android.viewmodel.CapturesViewModel = viewModel()

        NavHost(nav, startDestination = Screen.Status.route, Modifier.padding(innerPadding)) {
            composable(Screen.Status.route)   { StatusScreen() }
            composable(Screen.Passes.route)   {
                PassesScreen(
                    vm = passesVm,
                    onPassTap = { pass ->
                        passesVm.select(pass)
                        nav.navigate("pass_detail")
                    },
                )
            }
            composable(Screen.Rules.route)    { RulesScreen() }
            composable(Screen.Captures.route) {
                CapturesScreen(
                    vm = capturesVm,
                    onCaptureTap = { capture ->
                        capturesVm.select(capture)
                        nav.navigate("capture_detail")
                    },
                )
            }
            composable(Screen.Events.route)   { EventsScreen() }
            composable(Screen.Overhead.route) { OverheadScreen() }
            composable(Screen.Settings.route) { SettingsScreen(onSaved = { nav.navigate(Screen.Status.route) }) }

            composable("pass_detail") {
                PassDetailScreen(
                    vm = passesVm,
                    onBack = { nav.popBackStack() },
                )
            }
            composable("capture_detail") {
                CaptureDetailScreen(
                    vm = capturesVm,
                    onBack = { nav.popBackStack() },
                )
            }
        }
    }
}
