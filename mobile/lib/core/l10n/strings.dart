import 'package:flutter_riverpod/flutter_riverpod.dart';

/// App text in Somali and English. Somali is the default: the app's users are Somali-speaking
/// parents and drivers. One class, plain getters, no code generation.
class Strings {
  final bool so;
  const Strings(this.so);

  String _(String somali, String english) => so ? somali : english;

  // ---- general
  String get appName => 'RAAD';
  String get retry => _('Isku day mar kale', 'Try again');
  String get cancel => _('Jooji', 'Cancel');
  String get save => _('Kaydi', 'Save');
  String get send => _('Dir', 'Send');
  String get confirm => _('Xaqiiji', 'Confirm');
  String get close => _('Xir', 'Close');
  String get loading => _('Waa la soo rarayaa…', 'Loading…');
  String get noConnection => _(
        'Lama xiriiri karo server-ka RAAD. Hubi internet-kaaga.',
        'Could not reach the RAAD server. Check your connection.',
      );
  String get somethingWrong => _('Wax baa khaldamay.', 'Something went wrong.');
  String get notAvailable => _('Lama hayo', 'Not available');
  String get today => _('Maanta', 'Today');
  String get tomorrow => _('Berri', 'Tomorrow');
  String get yesterday => _('Shalay', 'Yesterday');
  String get language => _('Luqadda', 'Language');
  String get somali => 'Soomaali';
  String get english => 'English';

  // ---- auth
  String get identifierLabel =>
      _('Email ama lambarka taleefanka', 'Email or phone number');
  String get passwordLabel => _('Furaha sirta ah', 'Password');
  String get signIn => _('Gal', 'Sign in');
  String get signOut => _('Ka bax', 'Sign out');
  String get signInSubtitle =>
      _('La soco baska ardayda si toos ah', 'Follow the school bus, live');
  String get changePasswordTitle =>
      _('Beddel furaha sirta ah', 'Change your password');
  String get changePasswordIntro => _(
        'Waxaad ku gashay furo ku-meel-gaar ah. Dooro mid cusub si aad u sii wadato.',
        'You signed in with a temporary password. Choose a new one to continue.',
      );
  String get newPassword => _('Furaha cusub', 'New password');
  String get repeatPassword =>
      _('Ku celi furaha cusub', 'Repeat the new password');
  String get passwordsDiffer =>
      _('Labada furo isma laha.', 'The two passwords do not match.');
  String get passwordTooShort =>
      _('Furuhu waa inuu ka badnaadaa 8 xaraf.', 'Use at least 8 characters.');
  String get unsupportedRole => _(
        'Akoonkan laguma isticmaali karo app-ka. Waalidka iyo darawallada oo keliya.',
        'This account cannot use the mobile app. Parent and Driver accounts only.',
      );
  String get sessionExpired => _('Fadhigaagu wuu dhacay. Mar kale gal.',
      'Your session expired. Please sign in again.');

  // ---- navigation
  String get navHome => _('Bogga hore', 'Home');
  String get navHistory => _('Taariikhda', 'History');
  String get navNotifications => _('Ogeysiisyada', 'Notifications');
  String get navProfile => _('Akoonka', 'Profile');
  String get navToday => _('Maanta', 'Today');
  String get navTrips => _('Safarrada', 'Trips');
  String get navMore => _('Wax kale', 'More');

  // ---- trip status
  String tripStatus(String status) {
    switch (status) {
      case 'scheduled':
        return _('La qorsheeyay', 'Scheduled');
      case 'in_progress':
        return _('Safar ayuu ku jiraa', 'On trip');
      case 'interrupted':
        return _('Waa la hakiyay', 'Interrupted');
      case 'completed':
        return _('Wuu dhammaaday', 'Completed');
      case 'cancelled':
        return _('Waa la joojiyay', 'Cancelled');
      default:
        return status;
    }
  }

  String tripType(String type) => type == 'morning'
      ? _('Subaxnimo', 'Morning')
      : _('Galabnimo', 'Afternoon');

  String get noTripNow =>
      _('Baska hadda safar kuma jiro', 'The bus is not on a trip now');
  String get cancelledReason => _('Sababta', 'Reason');
  String get plannedDeparture => _('Waqtiga bixitaanka', 'Planned departure');

  // ---- parent
  String get myChildren => _('Carruurtayda', 'My children');
  String get noChildren => _(
        'Wali carruur laguma xirin akoonkaaga. La xiriir dugsiga.',
        'No children are linked to your account yet. Contact the school.',
      );
  String get bus => _('Baska', 'Bus');
  String get route => _('Jidka', 'Route');
  String get pickupStop => _('Goobta qaadista', 'Pickup stop');
  String get dropoffStop => _('Goobta dejinta', 'Dropoff stop');
  String get noAssignment => _(
        'Ilmahan wali bas looma qoondeyn.',
        'This child has not been assigned to a bus yet.',
      );
  String get noBusYet => _('Bas wali looma qoondeyn', 'No bus assigned yet');
  String get trackBus => _('La soco baska', 'Track the bus');
  String get liveLocation => _('Goobta baska', 'Bus location');
  String get live => _('Toos', 'Live');
  String get busOnTripNow =>
      _('Basku hadda wuu socdaa', 'The bus is on its way');
  String get todaysTrips => _('Safarrada maanta', "Today's trips");
  String get noTripsToday => _('Maanta safar ma jiro', 'No trips today');
  String get latestNotification =>
      _('Ogeysiiskii u dambeeyay', 'Latest notification');
  String get trackingOnlyOnTrip => _(
        'Goobta baska waxaa la arki karaa marka uu safar ku jiro oo keliya.',
        'The bus location is shown only while it is on a trip.',
      );
  String get waitingForPosition =>
      _('Waxaa la sugayaa goobta baska…', 'Waiting for the bus location…');
  String get tripEnded => _('Safarku wuu dhammaaday.', 'The trip has ended.');
  String get trackingDenied => _(
        'Goobta baska hadda lama heli karo.',
        'The bus location is not available right now.',
      );
  String get connectionLost => _('Xiriirkii wuu go\'ay. Dib ayaa loo xirayaa…',
      'Connection lost. Reconnecting…');
  String lastUpdated(String when) =>
      _('Markii u dambeysay: $when', 'Last updated: $when');
  String get staleLocation =>
      _('Goobtani waa mid hore', 'This location may be out of date');
  String get noGpsFix =>
      _('Basku wali GPS ma helin', 'The bus has no GPS fix yet');
  String distanceToStop(String distance) =>
      _('$distance ayuu u jiraa goobtaada', '$distance from your stop');
  String speed(String kph) =>
      _('Xawaaraha: $kph km/saacaddii', 'Speed: $kph km/h');
  String get mapUnavailable => _(
        'Khariidadda lama heli karo. Goobta hoos ayaa lagu muujiyay.',
        'The map is unavailable. The location is shown below.',
      );
  String get historyTitle => _('Taariikhda safarrada', 'Trip history');
  String get historyNote => _(
        'Halkan waxaa ka muuqda safarrada baska ilmahaaga. RAAD ma diiwaangeliso in ilmuhu fuulay iyo in kale.',
        "These are the trips of your child's bus. RAAD does not record whether a child boarded.",
      );
  String get noHistory => _('Wali safar ma jiro', 'No trips yet');
  String get watchVideo => _('Daawo muuqaalka baska', 'Watch the bus camera');

  // ---- notifications
  String get transportTab => _('Baska', 'Bus');
  String get schoolTab => _('Dugsiga', 'School');
  String get noNotifications => _('Ogeysiis ma jiro', 'No notifications');
  String get markAllRead => _('Dhammaan akhri', 'Mark all read');
  String notificationTitle(String type, String? kind, String fallback) {
    switch (kind ?? type) {
      case 'trip_started':
        return _('Safarkii baska wuu bilaabmay', 'The bus trip has started');
      case 'trip_completed':
        return _('Safarkii baska wuu dhammaaday', 'The bus trip has ended');
      case 'approaching_stop':
        return _('Basku wuu soo dhow yahay', 'The bus is approaching');
      case 'arrived_org':
        return _('Basku wuu gaaray dugsiga', 'The bus has arrived at school');
      case 'trip_cancelled':
        return _('Safar waa la joojiyay', 'A trip was cancelled');
      case 'cover_assigned':
        return _('Waxaad beddeleysaa darawal kale', 'You are covering a bus');
      default:
        return fallback;
    }
  }

  String? notificationBody(String type, String? kind) {
    switch (kind ?? type) {
      case 'trip_started':
        return _(
            'Baska ilmahaaga wuu dhaqaaqay.', "Your child's bus has set off.");
      case 'trip_completed':
        return _('Baska ilmahaaga safarkiisii wuu dhammeeyay.',
            "Your child's bus has finished its trip.");
      case 'approaching_stop':
        return _('Baska ilmahaaga wuxuu ku soo dhow yahay goobtaada.',
            "Your child's bus is close to your stop.");
      case 'arrived_org':
        return _('Baska ilmahaaga wuxuu gaaray dugsiga.',
            "Your child's bus has arrived at school.");
      default:
        return null;
    }
  }

  // ---- driver
  String get myTrips => _('Safarradayda', 'My trips');
  String get upcoming => _('Kuwa soo socda', 'Upcoming');
  String get past => _('Kuwii hore', 'Past');
  String get startTrip => _('Bilow safarka', 'Start trip');
  String get endTrip => _('Dhammee safarka', 'End trip');
  String get startTripConfirm =>
      _('Ma bilaabaysaa safarkan hadda?', 'Start this trip now?');
  String get endTripConfirm =>
      _('Ma dhammeynaysaa safarkan?', 'End this trip?');
  String get coverBadge => _('Beddel', 'Cover');
  String get coverNote => _(
        'Safarkan waxaad ku beddeleysaa darawal kale.',
        'You are standing in for another driver on this trip.',
      );
  String get tripDetails => _('Faahfaahinta safarka', 'Trip details');
  String get stops => _('Goobaha', 'Stops');
  String get passengers => _('Ardayda', 'Students');
  String get noPassengers =>
      _('Arday laguma qorin safarkan', 'No students on this trip');
  String get crew => _('Shaqaalaha baska', 'Bus crew');
  String get noCrew => _('Shaqaale lama qorin', 'No crew recorded');
  String get you => _('Adiga', 'You');
  String get substitute => _('Beddel', 'Substitute');
  String get documents => _('Dukumentiyadayda', 'My documents');
  String get noDocuments =>
      _('Dukumenti lama diiwaangelin', 'No documents recorded');
  String get compliant => _('Wax walba waa sax', 'Everything is in order');
  String get notCompliant =>
      _('Dukumenti ayaa maqan ama dhacay', 'A document is missing or expired');
  String expiresOn(String day) => _('Wuu dhacayaa: $day', 'Expires: $day');
  String daysLeft(int days) => days < 0
      ? _('Wuu dhacay', 'Expired')
      : _('$days maalmood ayaa u haray', '$days days left');
  String get unavailability =>
      _('Maalmaha aanan shaqeyn karin', 'My unavailability');
  String get reportUnavailability =>
      _('Sheeg inaadan iman karin', 'Report unavailability');
  String get unavailabilityNote => _(
        'Xafiiska ayaa la ogeysiinayaa si beddel loo diyaariyo.',
        'The office is told so that cover can be arranged.',
      );
  String get firstDay => _('Maalinta koowaad', 'First day');
  String get lastDay => _('Maalinta u dambeysa', 'Last day');
  String get reason => _('Sababta', 'Reason');
  String get note => _('Faahfaahin (ikhtiyaari)', 'Note (optional)');
  String unavailabilityReason(String reason) {
    switch (reason) {
      case 'sick':
        return _('Xanuun', 'Sick');
      case 'personal':
        return _('Arrin shakhsi ah', 'Personal');
      case 'training':
        return _('Tababar', 'Training');
      default:
        return _('Wax kale', 'Other');
    }
  }

  String get withdraw => _('Ka noqo', 'Withdraw');
  String get withdrawn => _('Waa laga noqday', 'Withdrawn');
  String get covered => _('Beddel waa la helay', 'Cover arranged');
  String get noUnavailability =>
      _('Waxba lama diiwaangelin', 'Nothing recorded');
  String get incidents => _('Dhacdooyinka', 'Incidents');
  String get reportIncident => _('Soo sheeg dhacdo', 'Report an incident');
  String get noIncidents => _(
      'Dhacdo aad soo sheegtay ma jirto', 'You have not reported any incident');
  String get incidentTitle => _('Maxaa dhacay?', 'What happened?');
  String get incidentDescription => _('Faahfaahin', 'Details');
  String get incidentCategory => _('Nooca', 'Type');
  String get incidentSeverity => _('Culayska', 'Severity');
  String get incidentTrip => _('Safarka (ikhtiyaari)', 'Trip (optional)');
  String get titleTooShort =>
      _('Qor ugu yaraan 3 xaraf.', 'Write at least 3 characters.');
  String incidentCategoryName(String category) {
    switch (category) {
      case 'accident':
        return _('Shil', 'Accident');
      case 'breakdown':
        return _('Baskii oo xumaaday', 'Breakdown');
      case 'medical':
        return _('Caafimaad', 'Medical');
      case 'behaviour':
        return _('Dhaqan', 'Behaviour');
      case 'near_miss':
        return _('Shil ku dhowaaday', 'Near miss');
      case 'delay':
        return _('Daahid', 'Delay');
      case 'student_left_behind':
        return _('Arday laga tegay', 'Student left behind');
      default:
        return _('Wax kale', 'Other');
    }
  }

  String severityName(String severity) {
    switch (severity) {
      case 'low':
        return _('Yar', 'Low');
      case 'high':
        return _('Sare', 'High');
      case 'critical':
        return _('Aad u daran', 'Critical');
      default:
        return _('Dhexe', 'Medium');
    }
  }

  String incidentStatus(String status) {
    switch (status) {
      case 'open':
        return _('Waa la helay', 'Received');
      case 'investigating':
        return _('Waa la baarayaa', 'Being looked into');
      case 'resolved':
        return _('Waa la xalliyay', 'Resolved');
      case 'closed':
        return _('Waa la xiray', 'Closed');
      default:
        return status;
    }
  }

  String get sent => _('Waa la diray', 'Sent');
  String get profile => _('Akoonkayga', 'My account');
  String get phone => _('Taleefan', 'Phone');
  String get email => 'Email';
  String get roleParent => _('Waalid', 'Parent');
  String get roleDriver => _('Darawal', 'Driver');
  String get gpsFromBus => _(
        'Goobta baska waxaa laga helaa qalabka baska ku rakiban, ma aha taleefankaaga.',
        'The bus location comes from the device on the bus, not from your phone.',
      );
}

/// 'so' or 'en'.
final languageProvider = StateProvider<String>((ref) => 'so');

final stringsProvider =
    Provider<Strings>((ref) => Strings(ref.watch(languageProvider) == 'so'));
