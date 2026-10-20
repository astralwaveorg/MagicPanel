plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "top.magichub.panel"
    compileSdk = 35

    defaultConfig {
        applicationId = "top.magichub.panel"
        // Android 7.0 起：覆盖小米 17 Pro Max / 一加 13 等 Android 15/16 设备
        minSdk = 24
        targetSdk = 35
        versionCode = 2
        versionName = "1.0.1"
        resourceConfigurations += listOf("zh", "zh-rCN", "en")
    }

    signingConfigs {
        create("release") {
            storeFile = file("magicpanel.keystore")
            storePassword = "magicpanel"
            keyAlias = "magicpanel"
            keyPassword = "magicpanel"
            // v1 + v2 + v3 全开：覆盖各家厂商 ROM 的安装器
            enableV1Signing = true
            enableV2Signing = true
            enableV3Signing = true
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            signingConfig = signingConfigs.getByName("release")
        }
        debug {
            applicationIdSuffix = ".debug"
        }
    }

    buildFeatures {
        viewBinding = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    packaging {
        resources {
            excludes += setOf("/META-INF/{AL2.0,LGPL2.1}", "META-INF/DEPENDENCIES")
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.1.0")
    implementation("com.google.android.material:material:1.12.0")
}
