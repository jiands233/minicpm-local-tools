// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "MiniCPMClipboard", platforms: [.macOS(.v13)],
    products: [.executable(name: "MiniCPMClipboard", targets: ["MiniCPMClipboard"])],
    targets: [.executableTarget(name: "MiniCPMClipboard", linkerSettings: [.linkedFramework("AppKit"), .linkedFramework("Carbon")])]
)
