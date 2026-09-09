// QQ 音乐设置页
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
import "../../controls"

ScrollView {
    id: root
    clip: true

    ColumnLayout {
        width: root.availableWidth
        spacing: Theme.spacingLg

        Text {
            text: "QQ 音乐"
            font.pixelSize: Theme.fontSizeXl
            font.weight: Font.DemiBold
            color: Theme.textPrimary
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "账号"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                Text {
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.qqMusicLoginStatus : "未登录"
                    font.pixelSize: Theme.fontSizeSm
                    color: text.startsWith("已登录") ? Theme.success : Theme.textSecondary
                }

                XComboBox {
                    id: loginTypeCombo
                    Layout.preferredWidth: 130
                    model: ["手机 QQ", "微信", "QQ 音乐 App"]
                    enabled: settingsModel && !settingsModel.qqMusicLoginBusy
                    font.pixelSize: Theme.fontSizeSm
                }

                XButton {
                    text: settingsModel && settingsModel.qqMusicLoginBusy ? "登录中…" : "扫码登录"
                    enabled: settingsModel && !settingsModel.qqMusicLoginBusy
                    onClicked: {
                        var types = ["qq", "wx", "mobile"]
                        settingsModel.startQqMusicLogin(types[loginTypeCombo.currentIndex])
                    }
                }

                XButton {
                    text: "退出"
                    variant: "secondary"
                    enabled: settingsModel && settingsModel.qqMusicLoginStatus.startsWith("已登录")
                    onClicked: settingsModel.logoutQqMusic()
                }
            }

            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 220
                Layout.preferredHeight: 220
                visible: settingsModel && settingsModel.qqMusicQrSource.length > 0
                color: "white"
                radius: Theme.radiusMd
                border.width: 1
                border.color: Theme.border

                Image {
                    anchors.fill: parent
                    anchors.margins: Theme.spacingSm
                    source: settingsModel ? settingsModel.qqMusicQrSource : ""
                    fillMode: Image.PreserveAspectFit
                    cache: false
                }
            }

            Text {
                Layout.fillWidth: true
                visible: settingsModel && settingsModel.qqMusicQrSource.length > 0
                text: "请使用所选客户端扫码，并在手机上确认。二维码 3 分钟后过期。"
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                font.pixelSize: Theme.fontSizeSm
                color: Theme.textSecondary
            }

            Text {
                Layout.fillWidth: true
                text: "未登录时可搜索并播放官方试听；登录后按账号版权和会员权限获取完整音源。凭据仅保存在本机配置中。"
                wrapMode: Text.WordWrap
                font.pixelSize: Theme.fontSizeXs
                color: Theme.textPlaceholder
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "播放偏好"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                rowSpacing: Theme.spacingMd
                columnSpacing: Theme.spacingLg

                Text {
                    text: "默认音质"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 120
                }
                XComboBox {
                    id: musicQualityCombo
                    Layout.preferredWidth: 150
                    model: ["320k", "128k"]
                    property var qualityValues: ["320k", "128k"]
                    currentIndex: {
                        var q = settingsModel ? settingsModel.musicDefaultQuality : "320k"
                        var idx = qualityValues.indexOf(q)
                        return idx >= 0 ? idx : 0
                    }
                    onActivated: function(index) {
                        if (settingsModel) settingsModel.musicDefaultQuality = qualityValues[index]
                    }
                    font.pixelSize: Theme.fontSizeSm
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
