// build.gradle.kts — корневой проект
plugins {
    id("com.android.application") version "8.2.0" apply false
    id("com.chaquo.python") version "15.0.1" apply false
}

tasks.register("clean", Delete::class) {
    delete(rootProject.layout.buildDirectory)
}