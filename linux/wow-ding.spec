Name:           wow-ding
Version:        1.4.0
Release:        1
Summary:        WoW Forever level-up notifications for Discord
# The upstream release does not declare a license.
License:        LicenseRef-Unknown
URL:            https://github.com/aelder/wow-ding
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz#/%{name}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  desktop-file-utils
Requires:       python3 >= 3.10
Requires:       python3-pillow
Requires:       python3-tkinter
Requires:       /usr/bin/secret-tool
Requires:       ca-certificates
Recommends:     gnome-keyring

%description
Watch local WoW Forever screenshots from a Wine or Proton installation and
send character names and levels to Discord using a desktop keyring webhook.

%prep
%setup -q

%build

%install
app=%{buildroot}%{_datadir}/%{name}
install -d "$app/Ding" %{buildroot}%{_bindir}
install -m 0644 addon.py hook.py marker.py watch.py linux_app.py linux_ui.py "$app/"
install -m 0644 Ding/Ding.lua Ding/Ding.toc "$app/Ding/"
printf '%%s\n' '#!/bin/sh' 'exec /usr/bin/python3 %{_datadir}/%{name}/linux_app.py "$@"' > %{buildroot}%{_bindir}/%{name}
chmod 0755 %{buildroot}%{_bindir}/%{name}
desktop-file-install --dir=%{buildroot}%{_datadir}/applications linux/wow-ding.desktop

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/wow-ding.desktop

%files
%{_bindir}/%{name}
%{_datadir}/%{name}/
%{_datadir}/applications/wow-ding.desktop

%changelog
* Sun Nov 08 2026 WoW Ding contributors <aelder@users.noreply.github.com> - 1.4.0-1
- Package the WoW Ding Linux desktop app for Fedora.
