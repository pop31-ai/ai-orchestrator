plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

android {
    namespace = "com.aiorchestrator.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.aiorchestrator.app"
        versionCode = 1
        versionName = "1.0.0"

        python {
            buildPython("/usr/bin/python3")
            pip {
                install("aiohttp")
                install("rich")
                install("click")
                install("pyyaml")
            }
        }

        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    flavorDimensions += "api"
    productFlavors {
        create("android8") {
            dimension = "api"
            versionNameSuffix = "-api26"
            minSdk = 26
            targetSdk = 28
        }
        create("android11") {
            dimension = "api"
            versionNameSuffix = "-api30"
            minSdk = 30
            targetSdk = 34
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
    }

    sourceSets {
        getByName("main") {
            python.srcDirs("src/main/python")
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.webkit:webkit:1.9.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")
    implementation("androidx.activity:activity-ktx:1.8.2")

    // Chaquopy Python
    runtimeOnly("com.chaquo.python:gradle:15.0.1")
}
